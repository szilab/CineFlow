import requests
from typing import Any
from urllib.request import urlopen
from system.logger import log
from bases.enums import RequestType


class RequestHandler:
    def __init__(self, base_url: str = None, headers: dict = None, params: dict = None) -> None:
        self.base_url = base_url or ""
        self.headers = headers or {}
        self.params = params or {}

    def make_request(
        self,
        method: RequestType,
        endpoint: str,
        headers: dict = None,
        params: dict = None,
        hide_errors: bool = False,
        **kwargs
    ) -> Any:
        url = f"{self.base_url}{endpoint}" if self.base_url else endpoint
        headers = {**self.headers, **(headers or {})}
        params = {**self.params, **(params or {})}
        try:
            response = requests.request(
                method=method.value,
                url=url,
                params=params,
                headers=headers,
                **kwargs
            )
            response.raise_for_status()
            log(f"{method} request to {url} succeeded.", level='DEBUG')
            return response
        except requests.exceptions.RequestException as e:
            if not hide_errors:
                log(f"Error during {method} request to {url}: {e}", level='ERROR')
            return None

    def get(self, endpoint: str, **kwargs) -> requests.Response:
        return self.make_request("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs) -> requests.Response:
        return self.make_request("POST", endpoint, **kwargs)

    def put(self, endpoint: str, **kwargs) -> requests.Response:
        return self.make_request("PUT", endpoint, **kwargs)

    @staticmethod
    def download_file(url, path: str) -> None:
        """Download a file from a URL and save it to a local path."""
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with open(path, 'wb') as file:
                for chunk in response.iter_content(chunk_size=8192):
                    file.write(chunk)
            log(f"File downloaded successfully from {url} to {path}.", level='DEBUG')
        except requests.RequestException as e:
            log(f"Failed to download file from {url}: {e}", level='ERROR')

    @staticmethod
    def get_file(url: str) -> bytes:
        """Retrieve file data from a URL."""
        try:
            with urlopen(url) as response:
                return response.read()
        except Exception as e:
            log(f"Failed to retrieve file from {url}: {e}", level='ERROR')
            return None
