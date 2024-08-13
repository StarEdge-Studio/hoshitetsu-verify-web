import requests
from colorama import Fore, Style, init

init(autoreset=True)
red = Fore.RED + Style.BRIGHT
green = Fore.GREEN + Style.BRIGHT
yellow = Fore.YELLOW + Style.BRIGHT
cyan = Fore.CYAN + Style.BRIGHT
reset = Style.RESET_ALL


ENDPOINT = "http://localhost:5000/api"
TOKEN = "your_verify_token"


def get_info(uuid_: str) -> requests.Response:
    data = {
        "uuid": uuid_,
        "token": TOKEN
    }
    response = requests.post(ENDPOINT, params={"action": "info"}, json=data)
    return response


def delete_user(uuid_: str) -> requests.Response:
    data = {
        "uuid": uuid_,
        "token": TOKEN
    }
    response = requests.post(ENDPOINT, params={"action": "delete"}, json=data)
    return response


def change_status(uuid_: str) -> requests.Response:
    data = {
        "uuid": uuid_,
        "token": TOKEN
    }
    response = requests.post(ENDPOINT, params={"action": "change"}, json=data)
    return response


def detail_info(data: dict):
    template = """Steam ID: {steam_id}
验证通过: {owned}
下载状态: {used}
下载时间: {used_at}
"""
    owned = "是" if data["owned"] else "否"
    used = yellow + "已下载" if data["used"] else green + "未下载"
    used_at = data["used_at"] if data["used"] else "未知"
    return template.format(steam_id=data["steam_id"], owned=owned, used=used, used_at=used_at)


while True:
    print("输入exit退出\n")
    uuid = input(cyan + "UUID> ")
    if uuid == "exit":
        break
    # noinspection PyBroadException
    try:
        resp = get_info(uuid)
        if resp.status_code == 200:
            print(green + "用户信息：")
            print(detail_info(resp.json()))
            while True:
                print("\n指令：\n"
                      "ref -> 刷新用户信息\n"
                      "del -> 删除用户\n"
                      "change -> 更改下载状态\n"
                      "exit -> 回到上一级")
                action = input(cyan + "操作>> ")
                if action == "exit":
                    break
                elif action == "ref":
                    resp = get_info(uuid)
                    if resp.status_code == 200:
                        print(green + "用户信息：")
                        print(detail_info(resp.json()))
                    else:
                        print(yellow + "未知错误")
                elif action == "del":
                    resp = delete_user(uuid)
                    if resp.status_code == 200:
                        print(green + "用户已删除")
                        break
                    else:
                        print(yellow + "未知错误")
                elif action == "change":
                    resp = change_status(uuid)
                    if resp.status_code == 200:
                        print(green + "用户下载状态已更改")
                        print(detail_info(get_info(uuid).json()))
                    else:
                        print(yellow + "未知错误")
                else:
                    print(yellow + "未知操作")
        elif resp.status_code == 400:
            print(yellow + "未知错误")
            raise Exception("未知错误")
        else:
            print(red + "用户不存在或未通过验证")
    except Exception as e:
        continue
