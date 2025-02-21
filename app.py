# app.py
from flask import Flask, redirect, url_for, session, request, render_template, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
import requests
from urllib.parse import urlencode, urlparse, parse_qs
# import warnings
import uuid
import os
from datetime import datetime, timedelta, timezone
import boto3

app = Flask(__name__)
app.secret_key = os.getenv('APP_SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
STEAM_OPENID_URL = 'https://steamcommunity.com/openid/login'
STEAM_WEB_API_URL = 'https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/'
STEAM_WEB_API_KEY = os.getenv('STEAM_WEB_API_KEY')
VERIFY_TOKEN = os.getenv('VERIFY_TOKEN')
R2_ID = os.getenv('R2_ID')
R2_SECRET = os.getenv('R2_SECRET')
endpoint_url = os.getenv('ENDPOINT_URL')
PROXY = os.getenv('PROXY', None)
# URL = os.getenv('URL')
APPID = 1567800

if not app.secret_key or not STEAM_WEB_API_KEY or not VERIFY_TOKEN:
    raise ValueError('Please set APP_SECRET_KEY, STEAM_WEB_API_KEY and VERIFY_TOKEN in environment variables')
# if not URL:
#     warnings.warn('URL is not set, using default value', UserWarning)
#     URL = 'http://localhost:5000'
if not R2_ID or not R2_SECRET:
    raise ValueError('Please set R2_ID and R2_SECRET in environment variables')

s3_client = boto3.client(
    's3',
    endpoint_url=endpoint_url,
    region_name="auto",
    aws_access_key_id=R2_ID,
    aws_secret_access_key=R2_SECRET
)


def get_client_ip():
    if request.headers.get('X-Forwarded-For'):
        # X-Forwarded-For 可能包含多个 IP 地址，取第一个非空的地址
        return request.headers.get('X-Forwarded-For').split(',')[0].strip()
    elif request.headers.get('X-Real-IP'):
        return request.headers.get('X-Real-IP')
    else:
        return request.remote_addr


# 初始化 Limiter，不设置默认限制
limiter = Limiter(
    key_func=get_client_ip,
    app=app,
    storage_uri="memory://"
)

db = SQLAlchemy(app)


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    steam_id = db.Column(db.String(20), unique=True, nullable=False)
    uuid = db.Column(db.String(36), unique=True, nullable=False)
    used = db.Column(db.Boolean, default=False, nullable=False)
    used_at = db.Column(db.TIMESTAMP, nullable=True)
    link = db.Column(db.Text, nullable=True)


# 初始化数据库
def create_tables():
    with app.app_context():
        db.create_all()


create_tables()

PROXIES = {
    'http': PROXY,
    'https': PROXY
}


@app.errorhandler(429)
def ratelimit_error(_e):
    return "Too many requests, please try again later.", 429


@app.errorhandler(500)
def internal_error(_e):
    return render_template('500.html'), 500


@app.route('/')
def index():
    return render_template('index.html')


# noinspection HttpUrlsUsage
@app.route('/login')
def login():
    steam_id = session.get('steam_id')
    user_uuid = session.get('uuid')
    if steam_id and user_uuid:
        # 如果已经登录，直接跳转到 profile 页面
        return redirect(url_for('profile'))
    params = {
        'openid.ns': 'http://specs.openid.net/auth/2.0',
        'openid.mode': 'checkid_setup',
        'openid.return_to': url_for('authenticate', _external=True),
        'openid.realm': url_for('index', _external=True),
        'openid.identity': 'http://specs.openid.net/auth/2.0/identifier_select',
        'openid.claimed_id': 'http://specs.openid.net/auth/2.0/identifier_select'
    }
    query_string = urlencode(params)
    auth_url = f"{STEAM_OPENID_URL}?{query_string}"
    return redirect(auth_url)


@app.route('/authenticate')
def authenticate():
    query = urlparse(request.url).query
    params = parse_qs(query)

    verify_params = {
        'openid.assoc_handle': params['openid.assoc_handle'][0],
        'openid.signed': params['openid.signed'][0],
        'openid.sig': params['openid.sig'][0],
        'openid.ns': params['openid.ns'][0],
        'openid.mode': 'check_authentication'
    }

    signed_fields = params['openid.signed'][0].split(',')
    for field in signed_fields:
        verify_params[f'openid.{field}'] = params[f'openid.{field}'][0]

    response = requests.post(STEAM_OPENID_URL, data=verify_params, proxies=PROXIES)
    if 'is_valid:true' in response.text:
        steam_id = params['openid.claimed_id'][0].split('/')[-1]

        session['steam_id'] = steam_id
        return redirect(url_for('waiting'))

    return render_template('failed.html')


@app.route('/waiting')
def waiting():
    steam_id = session.get('steam_id')
    if not steam_id:
        return redirect(url_for('index'))

    return render_template('waiting.html')


@app.route('/verify_ownership')
def verify_ownership():
    steam_id = session.get('steam_id')
    if not steam_id:
        return redirect(url_for('index'))

    user = User.query.filter_by(steam_id=steam_id).first()
    flag = verify_owner(steam_id)

    if flag is True:

        if not user:
            user = User(steam_id=steam_id, uuid=str(uuid.uuid4()))
            db.session.add(user)
            db.session.commit()

        session['uuid'] = user.uuid
        return redirect(url_for('profile'))
    elif flag is None and user:
        # 如果用户已存在，但验证失败
        # 则是用户验证后关闭了权限，继续进行
        session['uuid'] = user.uuid
        return redirect(url_for('profile'))
    elif flag is False:
        session.pop('steam_id', None)
        session.pop('uuid', None)
        return render_template('failed_false.html')
    else:
        session.pop('steam_id', None)
        session.pop('uuid', None)
        return render_template('failed_none.html')


@app.route('/profile')
def profile():
    steam_id = session.get('steam_id')
    user_uuid = session.get('uuid')
    if not steam_id or not user_uuid:
        return redirect(url_for('index'))

    return render_template('profile.html', steam_id=steam_id, user_uuid=user_uuid)


@app.route('/api/common', methods=['POST'])
@limiter.limit('10 per minute')
def api_common():
    data = request.get_json()

    if not data or 'uuid' not in data or 'token' not in data:
        return jsonify({'error': 'Missing parameters'}), 400
    user_uuid = data.get('uuid')
    token = data.get('token')
    if token != VERIFY_TOKEN:
        # return '验证失败，你没有权限访问此接口'
        return jsonify({'error': 'Unauthorized'}), 401
    user = User.query.filter_by(uuid=user_uuid).first()

    def get_info():
        if user:
            used_at = (user.used_at + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S') if user.used_at else None
            resp = {
                'steam_id': user.steam_id,
                'owned': True,
                'used': user.used,
                'used_at': used_at
            }
            return jsonify(resp), 200
        return jsonify({'error': 'User not found'}), 404

    def delete_user():
        if user:
            db.session.delete(user)
            db.session.commit()
            return jsonify({'message': 'User deleted'}), 200
        return jsonify({'error': 'User not found'}), 404

    def change():
        if user:
            user.used = not user.used
            user.used_at = None
            db.session.commit()
            return jsonify({'message': 'User status changed'}), 200
        return jsonify({'error': 'User not found'}), 404

    action = request.args.get('action')
    if action == 'info':
        return get_info()
    elif action == 'delete':
        return delete_user()
    elif action == 'change':
        return change()
    return jsonify({'error': 'Invalid action'}), 400


@app.route('/api/newlink', methods=['POST'])
@limiter.limit('10 per minute')
def api_new_link():
    data = request.get_json()
    if not data or 'token' not in data:
        return jsonify({'error': 'Missing parameters'}), 400
    token = data.get('token')
    if token != VERIFY_TOKEN:
        return jsonify({'error': 'Unauthorized'}), 401

    link = s3_client.generate_presigned_url(
        ClientMethod='get_object',
        Params={
            'Bucket': 'hoshitetsu',
            'Key': '星白公开版本2408R001-RC3.zip'
        },
        ExpiresIn=3600
    )
    return jsonify({'link': link}), 200


def verify_owner(steam_id):
    params = {
        'key': STEAM_WEB_API_KEY,
        'steamid': steam_id,
        'format': 'json'
    }
    response = requests.get(STEAM_WEB_API_URL, params=params, proxies=PROXIES)
    if response.status_code == 200:
        response = response.json()
        if not response['response']:
            # 无法获取游戏列表
            return None
        games = response['response']['games']
        for game in games:
            if game['appid'] == APPID:
                return True
        return False
    # assert False, f'Failed to get owned games: {response}'
    app.logger.error(f'Failed to get owned games: {response}')
    return None


@app.route('/get_file')
def get_file():
    steam_id = session.get('steam_id')
    user_uuid = session.get('uuid')
    if not steam_id or not user_uuid:
        return render_template('401.html'), 401
    user = User.query.filter_by(uuid=user_uuid).first()
    if not user:
        return render_template('401.html'), 401
    if user.used:
        # 如果用户已经下载过文件，返回 403
        return render_template('403.html'), 403
    temp_url = s3_client.generate_presigned_url(
        ClientMethod='get_object',
        Params={
            'Bucket': 'hoshitetsu',
            'Key': '星白公开版本2408R001-RC3.zip'
        },
        ExpiresIn=3600
    )
    user.used = True
    user.used_at = datetime.now(timezone.utc)
    user.link = temp_url
    db.session.commit()
    return redirect(temp_url)


if __name__ == '__main__':
    app.run(debug=True)
