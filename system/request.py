"""This module provides a class to handle requests."""


import os
import time
import hashlib
from typing import Optional
from dataclasses import dataclass
from json import JSONDecodeError
import requests
from system.logger import log
from system.database import Database as Db


@dataclass
class RequestResponse:
    """Dataclass to store the response of a request."""
    data: dict
    status: int
    cookies: dict


class RequestHandler:
    """Class to handle requests."""
    DEFAULT_HEADERS = {
        'Accept': 'application/json',
        'Content-Type': 'application/json;charset=utf-8',
    }

    def __init__(self, url: Optional[str] = None) -> None:
        """Initialize the request handler."""
        self._url = (url or '').rstrip('/')
        self._params = {}
        self._headers = self.DEFAULT_HEADERS
        self._rate_limiter = RateLimiter()
        self._cache_handler = CacheHandler(cache_time=0)

    def get(self, endpoint: str, **kwargs) -> RequestResponse:
        """Make a GET request"""
        return self._do('GET', endpoint=endpoint, **kwargs)

    def post(self, endpoint: str, data: dict, **kwargs) -> RequestResponse:
        """Make a POST request"""
        return self._do('POST', endpoint, data=data, **kwargs)

    def put(self, endpoint: str, data: dict, **kwargs) -> RequestResponse:
        """Make a PUT request"""
        return self._do('PUT', endpoint, data=data, **kwargs)

    def _do(self, method: str, endpoint: str, **kwargs) -> RequestResponse:
        full_url = f"{self._url}/{endpoint.lstrip('/')}"
        # merge default headers with user headers without overwriting critical keys
        kwargs['params'] = {**self._params, **kwargs.get("params", {})}
        kwargs['headers'] = {**self._headers, **kwargs.get("headers", {})}
        # return cached response if available
        if cached := self._cache_handler.read(method, full_url, **kwargs):
            return RequestResponse(data=cached, status=200, cookies={})
        # respect API rate limits
        self._rate_limiter.wait()
        # shoot the request
        try:
            response = requests.request(
                method=method,
                url=full_url,
                timeout=int(os.environ.get('REQUEST_TIMEOUT', '15')),
                **kwargs
            )
            response.raise_for_status()
        except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
            log(f"Request error '{full_url}': {e}", level='WARNING')
            return RequestResponse(data=None, status=0, cookies={})
        if not response:
            log(f"No response received for '{full_url}'", level='WARNING')
            return RequestResponse(data=None, status=0, cookies={})
        # try to parse the response as JSON
        try:
            data = response.json()
        except JSONDecodeError:
            log(f"Response is not JSON: {response.text}")
            data = response.text.strip()
        self._cache_handler.write(method, url=full_url, data=data, **kwargs)
        return RequestResponse(
            data=data,
            status=response.status_code,
            cookies=response.cookies.get_dict()
        )

    @property
    def params(self) -> dict:
        return self._params

    @params.setter
    def params(self, value: dict) -> None:
        if value:
            if isinstance(value, dict):
                self._params = value
        else:
            self._params = {}

    @property
    def headers(self) -> dict:
        return self._headers

    @headers.setter
    def headers(self, value: dict) -> None:
        if value:
            if isinstance(value, dict):
                self._headers = value
        else:
            self._headers = {}

    @property
    def rate_limit(self) -> float:
        return self._rate_limiter.min_interval

    @rate_limit.setter
    def rate_limit(self, value: float) -> None:
        self._rate_limiter.min_interval = max(value, 0)

    @property
    def cache_time(self) -> int:
        return self._cache_handler.cache_time

    @cache_time.setter
    def cache_time(self, value: int) -> None:
        self._cache_handler.cache_time = max(value, 0)


class CacheHandler:
    """Handles caching of request responses."""

    def __init__(self, cache_time: int = 0, db: Optional[Db] = None):
        self.cache_time = cache_time
        self._db = db or Db()

    def _hash(self, method: str, url: str, kwargs: dict) -> str:
        key = f"{method}:{url}:{kwargs}"
        return hashlib.md5(key.encode()).hexdigest()

    def read(self, method: str, url: str, **kwargs) -> Optional[dict]:
        """Read cached response from the database."""
        if self.cache_time <= 0:
            return None
        rhash = self._hash(method, url, kwargs)
        return self._db.get_request(rhash=rhash, expire=self.cache_time)

    def write(self, method: str, url: str, data: dict, **kwargs) -> None:
        """Write response to the cache."""
        if self.cache_time <= 0:
            return
        rhash = self._hash(method, url, kwargs)
        self._db.store_request(rhash=rhash, data=data)


class RateLimiter:
    """Simple rate limiter that ensures a minimum delay between actions."""

    def __init__(self, min_interval: float = 0.3):
        self.min_interval = max(float(os.environ.get('REQUEST_MIN_INTERVAL', min_interval)), 0)
        self._last_time = None

    def wait(self) -> None:
        """Wait if needed to enforce rate limit."""
        now = time.time()
        if self._last_time is not None:
            elapsed = now - self._last_time
            if elapsed < self.min_interval:
                wait_time = self.min_interval - elapsed
                log(f"Waiting {wait_time:.2f}s to respect rate limit.")
                time.sleep(wait_time)
        self._last_time = time.time()
