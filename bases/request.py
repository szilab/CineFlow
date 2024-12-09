"""This module provides a class to handle requests to a given URL."""

from typing import Any
from json import JSONDecodeError
from dataclasses import dataclass

import requests
from system.logger import log


@dataclass
class RequestResponse:
    """Dataclass to store the response of a request."""
    data: Any
    status: int
    cookies: dict


class RequestHandler:
    """Class to handle requests to a given URL."""

    def __init__(self, url: str) -> None:
        self._url = url

    def _raise(self, method: str, endpoint: str, **kwargs) -> Any:
        try:
            response = requests.request(
                method=method, url=f"{self._url}/{endpoint}",
                timeout=10,
                **kwargs
            )
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            log(f"Reqest error '{self._url}/{endpoint}': {e}", level='WARNING')
        return response

    def _process(self, response: requests.Response, key: str = None) -> Any:
        if response.status_code not in [200, 201, 202]:
            log(f"Unexpected status {response.status_code}, {response.text}", level='WARNING')
            return None
        try:
            json_response = response.json()
        except JSONDecodeError:
            log(f"Response is not JSON: {response.text}", level='DEBUG')
            return response.text.strip()
        if not key:
            return json_response
        return json_response.get(key, json_response)

    def _request(self, method: str, endpoint: str, key: str = None, **kwargs) -> RequestResponse:
        log(f"Making {method} request to {self._url}/{endpoint}", level='DEBUG')
        response = self._raise(method=method, endpoint=endpoint, **kwargs)
        data = self._process(response=response, key=key)
        return RequestResponse(
            data=data,
            status=response.status_code,
            cookies=response.cookies.get_dict()
        )

    def get(self, endpoint: str, key: str = None, **kwargs) -> RequestResponse:
        """Make a GET request to the given endpoint."""
        return self._request(method='GET', endpoint=endpoint, key=key, **kwargs)

    def post(self, endpoint: str, key: str = None, **kwargs) -> RequestResponse:
        """Make a POST request to the given endpoint."""
        return self._request(method='POST', endpoint=endpoint, key=key, **kwargs)

    def put(self, endpoint: str, key: str = None, **kwargs) -> RequestResponse:
        """Make a PUT request to the given endpoint."""
        return self._request(method='PUT', endpoint=endpoint, key=key, **kwargs)
