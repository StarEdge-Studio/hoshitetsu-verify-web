# app.py
from flask import Flask, redirect, url_for, session, request, render_template, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_limiter import Limiter
import requests
from urllib.parse import urlencode, urlparse, parse_qs
# import warnings
import uuid
import os

app = Flask(__name__)
app.secret_key = os.getenv('APP_SECRET_KEY')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
STEAM_OPENID_URL = 'https://steamcommunity.com/openid/login'
STEAM_WEB_API_URL = 'https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/'
STEAM_WEB_API_KEY = os.getenv('STEAM_WEB_API_KEY')
VERIFY_TOKEN = os.getenv('VERIFY_TOKEN')
# URL = os.getenv('URL')
APPID = 1567800

if not app.secret_key or not STEAM_WEB_API_KEY or not VERIFY_TOKEN:
    raise ValueError('Please set APP_SECRET_KEY, STEAM_WEB_API_KEY and VERIFY_TOKEN in environment variables')
# if not URL:
#     warnings.warn('URL is not set, using default value', UserWarning)
#     URL = 'http://localhost:5000'


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
    id = db.Column(db.Integer, primary_key=True)
    steam_id = db.Column(db.String(20), unique=True, nullable=False)
    uuid = db.Column(db.String(36), unique=True, nullable=False)


# 初始化数据库
def create_tables():
    with app.app_context():
        db.create_all()


create_tables()


@app.errorhandler(429)
def ratelimit_error(_e):
    return "Too many requests, please try again later.", 429


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/login')
def login():
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

    response = requests.post(STEAM_OPENID_URL, data=verify_params)
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


@app.route('/verify', methods=['POST'])
@limiter.limit('10 per minute')
def verify():
    data = request.get_json()
    if not data or 'uuid' not in data or 'token' not in data:
        return jsonify({'error': 'Missing parameters'}), 400
    user_uuid = data.get('uuid')
    token = data.get('token')
    if token != VERIFY_TOKEN:
        # return '验证失败，你没有权限访问此接口'
        return jsonify({'error': 'Unauthorized'}), 401
    user = User.query.filter_by(uuid=user_uuid).first()
    if user:
        return jsonify({'owned': True, 'message': '验证成功，该用户拥有游戏所有权'}), 200
    return jsonify({'owned': False, 'message': '验证失败，该用户没有游戏所有权或不存在'}), 200


def verify_owner(steam_id):
    params = {
        'key': STEAM_WEB_API_KEY,
        'steamid': steam_id,
        'format': 'json'
    }
    response = requests.get(STEAM_WEB_API_URL, params=params)
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
    assert False, f'Failed to get owned games: {response}'


if __name__ == '__main__':
    app.run(debug=True)
