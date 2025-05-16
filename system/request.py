"""This module provides a class to handle requests."""

from typing import Any
from dataclasses import dataclass
from json import JSONDecodeError
import requests
from system.logger import log


@dataclass
class RequestResponse:
    """Dataclass to store the response of a request."""
    data: dict
    status: int
    cookies: dict


class RequestHandler:
    """Class to handle requests."""

    def __init__(self,  url: str = None, params: dict = None, headers: dict = None) -> None:
        """Initialize the request handler."""
        self.url = url if url else ''
        self.params = params if params else {}
        self.headers = headers if headers else {
            'Accept': 'application/json',
            'Content-Type': 'application/json;charset=utf-8',
        }

    def _raise(
        self, method: str, endpoint: str, params: dict = None, headers: dict = None, **kwargs
    ) -> requests.Response:
        """Raise an exception if the request fails."""
        response = requests.request(
            method=method,
            url=self.url + endpoint,
            timeout=10,
            params={**self.params, **(params or {})},
            headers={**self.headers, **(headers or {})},
            **kwargs
        )
        try:
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            log(f"Reqest error '{self.url + endpoint}': {e}", level='WARNING')
            return response
        return response

    def _process(self, response: requests.Response) -> Any:
        """Process the response of a request."""
        if response.status_code not in [200, 201, 202]:
            log(f"Unexpected status {response.status_code}, {response.text}", level='WARNING')
            return None
        try:
            json_response = response.json()
        except JSONDecodeError:
            log(f"Reqest response is not JSON: {response.text}", level='DEBUG')
            return response.text.strip()
        log(f"Reqest response status code: {response.status_code}", level='DEBUG')
        return json_response

    def _do(
        self, method: str, endpoint: str, params: dict = None, headers: dict = None, **kwargs
    ) -> RequestResponse:
        """Make a request to a given endpoint."""
        log(f"Making {method} request to {endpoint}", level='DEBUG')
        response = self._raise(
            method=method, endpoint=endpoint, params=params, headers=headers, **kwargs
        )
        data = self._process(response=response)
        return RequestResponse(
            data=data,
            status=response.status_code,
            cookies=response.cookies.get_dict()
        )

    def get(
        self, endpoint: str, params: dict = None, headers: dict = None, **kwargs
    ) -> RequestResponse:
        """Make a GET request"""
        return self._do(
            method='GET', endpoint=endpoint, params=params, headers=headers, **kwargs
        )

    def post(
        self, endpoint: str, data: dict, params: dict = None, headers: dict = None, **kwargs
    ) -> RequestResponse:
        """Make a POST request"""
        return self._do(
            method='POST', endpoint=endpoint, data=data, params=params, headers=headers, **kwargs
        )

    def put(
        self, endpoint: str, data: dict, params: dict = None, headers: dict = None, **kwargs
    ) -> RequestResponse:
        """Make a PUT request"""
        return self._do(
            method='PUT', endpoint=endpoint, data=data, params=params, headers=headers, **kwargs
        )
