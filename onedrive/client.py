import requests
from rich.progress import (
    Progress,
    BarColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    SpinnerColumn,
    TaskProgressColumn,
    DownloadColumn
)
import time


class Client(object):
    """
    The Application class is the main class for the OFB Python SDK. It is used to create a new instance of the SDK.
    """
    def __init__(self, client_id: str, client_secret: str, refresh_token: str, redirect_uri: str,
                 disable_progress: bool = False):
        """
        The constructor for the Application class.

        :param client_id: The application ID.
        :param client_secret: The application secret.
        :param refresh_token: The refresh token. You can use the https://alist.nn.ci/tool/onedrive/request.html
        to get the refresh token, or get it by yourself.
        :param redirect_uri: The redirect URI, if you use the above tool,
        it should be "https://alist.nn.ci/tool/onedrive/callback".
        :param disable_progress: Disable the progress bar when uploading big files. Default is False.
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.redirect_uri = redirect_uri
        self.access_token = ""
        self.token_invalid_time = 0
        self.disable_progress = disable_progress

    def get_access_token(self):
        """
        Get the access token.
        :return: The access token.
        """
        if time.time() < self.token_invalid_time:
            return self.access_token
        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }
        body = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "redirect_uri": self.redirect_uri,
            "grant_type": "refresh_token"
        }
        response = requests.post("https://login.microsoftonline.com/common/oauth2/v2.0/token",
                                 headers=headers, data=body)
        if response.status_code >= 400:
            raise OperationFailedError(f"Failed to get access token: {response.status_code}. "
                                       f"Response: {response.text}")
        self.access_token = response.json()["access_token"]
        self.token_invalid_time = time.time() + response.json()["expires_in"]
        return self.access_token

    def upload_file(self, file: bytes, remote_file: str, auto_transfer: bool = False):
        """
        Upload a file to the OneDrive.\n
        Only support files that are less than 4MB, if you want to upload a big file,
        please use the upload_big_file method.
        :param auto_transfer: Automatically transfer the file to upload_big_file if the file is too big.
        :param file: The file content.
        :param remote_file: The remote file path, relative to the root folder. Start with "/", for example: "/test.txt".
        :return: The original response.
        """
        if len(file) > 4000000:
            if auto_transfer:
                return self.upload_big_file(file, remote_file)
            raise FileTooBigError("The file is too big. Please use the upload_big_file method.")
        access_token = self.get_access_token()
        headers = {
            "Authorization": "Bearer " + access_token
        }
        response = requests.put("https://graph.microsoft.com/v1.0/me/drive/root:" + remote_file + ":/content",
                                headers=headers, data=file)
        if response.status_code >= 400:
            raise OperationFailedError(f"Failed to upload file: {response.status_code}. Response: {response.text}")
        return response

    def upload_big_file(self, file: bytes, remote_file: str):
        """
        Upload a big file to the OneDrive.

        :param file: The file content.
        :param remote_file: The remote file path, relative to the root folder. Start with "/", for example: "/test.txt".
        :return: True if success, False if failed.
        """
        access_token = self.get_access_token()
        headers = {
            "Authorization": "Bearer " + access_token
        }
        chunk_size = 3276800
        size = len(file)
        if self.disable_progress:
            # 先创建上传会话
            data = {
                "item": {
                    "@microsoft.graph.conflictBehavior": "replace"
                }
            }
            response = requests.post("https://graph.microsoft.com/v1.0/me/drive/root:"
                                     + remote_file + ":/createUploadSession",
                                     headers=headers, json=data)
            if response.status_code != 200:
                raise OperationFailedError(f"Failed to upload session: {response.status_code}. "
                                           f"Response: {response.text}")
            upload_url = response.json()["uploadUrl"]
            for i in range(0, size, chunk_size):
                chunk = file[i:i + chunk_size]
                headers = {
                    "Content-Length": str(len(chunk)),
                    "Content-Range": "bytes " + str(i) + "-" + str(i + len(chunk) - 1) + "/" + str(size)
                }
                response = requests.put(upload_url, headers=headers, data=chunk)
                if response.status_code != 202:
                    break
        else:
            with Progress(
                    "{task.description}",
                    SpinnerColumn(),
                    BarColumn(),
                    # "{task.completed}/{task.total}",
                    DownloadColumn(),
                    # TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                    TaskProgressColumn(),
                    TimeElapsedColumn(),
                    "<",
                    TimeRemainingColumn(),
            ) as progress:
                task = progress.add_task("[cyan]Uploading...", total=size)
                # 先创建上传会话
                data = {
                    "item": {
                        "@microsoft.graph.conflictBehavior": "replace"
                    }
                }
                response = requests.post("https://graph.microsoft.com/v1.0/me/drive/root:"
                                         + remote_file + ":/createUploadSession",
                                         headers=headers, json=data)
                if response.status_code != 200:
                    raise OperationFailedError(f"Failed to upload session: {response.status_code}. "
                                               f"Response: {response.text}")
                upload_url = response.json()["uploadUrl"]
                for i in range(0, size, chunk_size):
                    chunk = file[i:i + chunk_size]
                    headers = {
                        "Content-Length": str(len(chunk)),
                        "Content-Range": "bytes " + str(i) + "-" + str(i + len(chunk) - 1) + "/" + str(size)
                    }
                    response = requests.put(upload_url, headers=headers, data=chunk)
                    progress.update(task, advance=chunk_size)
                    progress.refresh()
                    if response.status_code != 202:
                        break
        if response.status_code == 200 or response.status_code == 201:
            return True
        else:
            raise OperationFailedError(f"Failed to upload file: {response.status_code}. Response: {response.text}")

    def create_folder(self, folder_name: str, do_if_exist: str = "rename"):
        """
        Create a folder in the OneDrive.

        :param folder_name: The folder name/path, relative to the root folder.
            Start with "/" , for example: "/test/test2".
        :param do_if_exist: The behavior if the folder exists. rename | fail | replace. Default is rename.
        :return: The original response.
        """
        access_token = self.get_access_token()
        if folder_name.count("/") == 1:
            path = "root"
        else:
            path = folder_name.split("/")[:-1]
            path = "/".join(path)
        folder_name = folder_name.split("/")[-1]
        headers = {
            "Authorization": "Bearer " + access_token,
            "Content-Type": "application/json"
        }
        data = {
            "name": folder_name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": do_if_exist
        }
        if path == "root":
            response = requests.post("https://graph.microsoft.com/v1.0/me/drive/root/children",
                                     headers=headers, json=data)
        else:
            response = requests.post("https://graph.microsoft.com/v1.0/me/drive/root:" + path + ":/children",
                                     headers=headers, json=data)
        if response.status_code >= 400:
            raise OperationFailedError(f"Failed to create folder: {response.status_code}. Response: {response.text}")
        return response

    def download_file(self, remote_file: str):
        """
        Download a file from the OneDrive.

        :param remote_file: The remote file path, relative to the root folder. Start with "/", for example: "/test.txt".
        :return: The file content.
        """
        access_token = self.get_access_token()
        headers = {
            "Authorization": "Bearer " + access_token
        }
        response = requests.get("https://graph.microsoft.com/v1.0/me/drive/root:" + remote_file + ":/content",
                                headers=headers)
        if response.status_code >= 400:
            raise OperationFailedError(f"Failed to download file: {response.status_code}. Response: {response.text}")
        return response.content

    def get_temp_link(self, remote_file: str):
        """
        Get a temporary link (valid for few minutes) to download a file from the OneDrive.
        :param remote_file: The remote file path, relative to the root folder. Start with "/", for example: "/test.txt".
        :return: A temporary link.
        """
        access_token = self.get_access_token()
        headers = {
            "Authorization": "Bearer " + access_token
        }
        response = requests.get("https://graph.microsoft.com/v1.0/me/drive/root:" + remote_file + ":/content",
                                headers=headers, allow_redirects=False)
        if response.status_code >= 400:
            raise OperationFailedError(f"Failed to get temporary link: {response.status_code}. "
                                       f"Response: {response.text}")
        return response.headers["Location"]

    def get_file_id(self, remote_file: str):
        """
        Get the file ID. Will be used in the future.
        :param remote_file: The remote file path, relative to the root folder. Start with "/", for example: "/test.txt".
        :return: The file ID.
        """
        access_token = self.get_access_token()
        headers = {
            "Authorization": "Bearer " + access_token
        }
        response = requests.get("https://graph.microsoft.com/v1.0/me/drive/root:" + remote_file,
                                headers=headers)
        if response.status_code >= 400:
            raise OperationFailedError(f"Failed to get file ID: {response.status_code}. Response: {response.text}")
        return response.json()["id"]

    def delete_file(self, remote_file: str):
        """
        Move a file to the recycle bin in the OneDrive.
        :param remote_file: The remote file path, relative to the root folder. Start with "/", for example: "/test.txt".
        :return: The original response.
        """
        access_token = self.get_access_token()
        headers = {
            "Authorization": "Bearer " + access_token
        }
        response = requests.delete("https://graph.microsoft.com/v1.0/me/drive/root:" + remote_file,
                                   headers=headers)
        if response.status_code >= 400:
            raise OperationFailedError(f"Failed to delete file: {response.status_code}. Response: {response.text}")
        return response

    def search_files(self, keyword: str):
        """
        Search files in the OneDrive.
        :param keyword: The keyword to search.
        :return: A list of files.
        """
        access_token = self.get_access_token()
        headers = {
            "Authorization": "Bearer " + access_token
        }
        url = f"https://graph.microsoft.com/v1.0/me/drive/root/search(q='{keyword}')"
        result = []
        while True:
            response = requests.get(url, headers=headers)
            if response.status_code >= 400:
                raise OperationFailedError(f"Failed to search files: {response.status_code}. Response: {response.text}")
            data = response.json()
            result.extend(data["value"])
            if "@odata.nextLink" not in data:
                break
            url = data["@odata.nextLink"]
        return result


class OperationFailedError(Exception):
    """
    The OperationFailedError class is used to raise an exception when an operation failed.
    """
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


class FileTooBigError(Exception):
    """
    The FileTooBigError class is used to raise an exception when the file is too big.
    """
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)
