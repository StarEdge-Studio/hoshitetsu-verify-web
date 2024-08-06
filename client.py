import requests
from colorama import Fore, Style, init

init(autoreset=True)
red = Fore.RED + Style.BRIGHT
green = Fore.GREEN + Style.BRIGHT
yellow = Fore.YELLOW + Style.BRIGHT


ENDPOINT = "http://localhost:5000/verify"
TOKEN = "your_verify_token"


def verify_ownership(uuid_):
    data = {
        "uuid": uuid_,
        "token": TOKEN
    }
    response = requests.post(ENDPOINT, json=data, headers={"Content-Type": "application/json"})
    return response.json()


while True:
    uuid = input("请输入UUID：")
    if uuid == "exit":
        break
    resp = verify_ownership(uuid)
    if resp.get("owned"):
        print(green + resp.get("message"))
    elif resp.get("owned") is False:
        print(red + resp.get("message"))
    else:
        assert False, f"{red}Failed to verify ownership: {resp}"
