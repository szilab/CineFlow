"""qBittorrent WebAPI consumer module."""

from http.cookies import SimpleCookie
from urllib.parse import urlsplit, urlunsplit
from typing import Any, Dict, List
from cineflow.core.bases.module import ConsumerBase
from cineflow.core.logger import log
from cineflow.utils.misc import media_title, media_year, sanitize_name


class QBittorrent(ConsumerBase):
    """
    qBittorrent WebAPI consumer module.

    Configuration:
        - url: qBittorrent base URL (e.g., http://localhost:8080)
        - username: qBittorrent username (optional)
        - password: qBittorrent password (optional)
        - directory: download directory mapped to savepath (optional)
        - category: qBittorrent category (optional)
        - tags: qBittorrent tags (optional)
    """

    FORM_HEADERS = {'Content-Type': 'application/x-www-form-urlencoded'}

    def __init__(self, config: dict = None) -> None:
        super().__init__(config=config)
        self.cache_time = 0
        self._handler.ok_statuses = {200, 201, 202, 204, 403, 409}
        self._handler.headers = {'Accept': 'application/json'}
        self._sid = None
        self._auth_cookies = {}
        self._headers = {'Referer': self._referer(), 'Origin': self._origin()}
        self._data_mappings = {
            'title': ['name'],
            'year': ['name'],
            'status': ['state'],
            'percent_done': ['progress'],
        }
        self._data_transforms = {
            'title': media_title,
            'year': media_year,
        }
        if self.cfg('username', default=None):
            self._login()

    def get(self, query: Any = None) -> List[Dict] | None:
        """Get torrents from the qBittorrent API."""
        response = self._api_request('GET', 'api/v2/torrents/info')
        if response is None:
            log("Failed to retrieve torrents from qBittorrent API.", level='ERROR')
            return None
        if not isinstance(response, list):
            log(f"Invalid response from qBittorrent API: {response}", level='WARNING')
            return None
        if not response:
            log("No torrents found in qBittorrent.", level='WARNING')
            return []
        results = []
        for item in response:
            if media := self.map(item=item):
                if media and query and query in sanitize_name(name=media.get('title')):
                    results.append(media)
                elif media and not query:
                    results.append(media)
                else:
                    log(f"Skipping item '{item.get('name')}' invalid or not match.", level='DEBUG')
        return results

    def search(self, media: dict) -> dict:
        """Search media for the given title in torrent list."""
        results = self.get(query=sanitize_name(name=media.get('title')))
        if match := self.match(results=results, media=media):
            return match
        if media.get('alttitle'):
            results = self.get(query=sanitize_name(name=media.get('alttitle')))
            return self.match(results=results, media=media)
        return None

    def put(self, data: List[Dict]) -> List[Dict]:
        """Add torrent URLs to the qBittorrent download list."""
        if not data:
            log("No data provided to add to qBittorrent.", level='MSG')
            return data
        for media in data:
            if params := self._prepare_params(media=media):
                response = self._api_request('POST', 'api/v2/torrents/add', data=params, form=True)
                self._handle_response(media=media, response=response)
        return data

    def _prepare_params(self, media: dict) -> dict | None:
        """Prepare qBittorrent torrent-add form parameters."""
        link = media.get('link')
        if not link:
            log(f"Item '{media.get('title')}' is missing torrent link.", level='WARNING')
            media['qbittorrent_status'] = 'invalid_link'
            return None
        if not link.startswith(('magnet:', 'http://', 'https://')):
            log(f"Unsupported torrent link: {link}", level='ERROR')
            media['qbittorrent_status'] = 'invalid_link'
            return None

        params = {'urls': link}
        if self.cfg('directory'):
            params['savepath'] = self.cfg('directory')
        if self.cfg('category'):
            params['category'] = self.cfg('category')
        if self.cfg('tags'):
            params['tags'] = self.cfg('tags')
        return params

    def _handle_response(self, media: dict, response: Any) -> None:
        """Handle the response from a qBittorrent add request."""
        if response is None:
            log(f"Failed to add torrent '{media.get('title')}' to qBittorrent.", level='ERROR')
            media['qbittorrent_status'] = 'error'
        elif str(response).lower() == 'ok.':
            log(f"Torrent '{media.get('title')}' added successfully to qBittorrent.", level='MSG')
            media['qbittorrent_status'] = 'added'
        elif str(response).lower() == 'fails.':
            log(f"Failed to add torrent '{media.get('title')}' to qBittorrent.", level='ERROR')
            media['qbittorrent_status'] = 'error'
        elif isinstance(response, dict) and response.get('success_count', 0) > 0:
            log(
                f"Torrent '{media.get('title')}' added successfully to qBittorrent.",
                level='MSG'
            )
            media['qbittorrent_status'] = 'added'
        elif isinstance(response, dict) and response.get('pending_count', 0) > 0:
            log(f"Torrent '{media.get('title')}' accepted by qBittorrent.", level='MSG')
            media['qbittorrent_status'] = 'added'
        elif isinstance(response, dict) and response.get('failure_count', 0) > 0:
            log(
                f"Failed to add torrent '{media.get('title')}' to qBittorrent: {response}",
                level='ERROR'
            )
            media['qbittorrent_status'] = 'error'
        else:
            log(
                f"Unexpected qBittorrent add response for '{media.get('title')}': {response}",
                level='ERROR'
            )
            media['qbittorrent_status'] = 'error'

    def _api_request(
        self, method: str, endpoint: str, data: dict = None, form: bool = False
    ) -> Any | None:
        """Make an authenticated qBittorrent WebAPI request with one 403 re-login retry."""
        for attempt in range(2):
            response = self._send_request(method=method, endpoint=endpoint, data=data, form=form)
            if response.status != 403:
                break
            if attempt == 0 and self.cfg('username', default=None):
                log("qBittorrent session expired; attempting one re-login.", level='WARNING')
                try:
                    self._login()
                except ValueError as exc:
                    log(str(exc), level='ERROR')
                    return None
                continue
            log(f"qBittorrent request forbidden for '{endpoint}'.", level='ERROR')
            return None
        if response.status == 0:
            return None
        return response.data

    def _send_request(self, method: str, endpoint: str, data: dict = None, form: bool = False):
        """Dispatch a request through RequestHandler."""
        kwargs = {'cookies': self._cookies(), 'headers': self._headers}
        if form:
            kwargs['files'] = self._multipart_fields(data=data or {})
            data = {}
        if method == 'GET':
            return self._handler.get(endpoint=endpoint, **kwargs)
        if method == 'POST':
            return self._handler.post(endpoint=endpoint, data=data or {}, **kwargs)
        raise ValueError(f"Unsupported qBittorrent request method: {method}")

    def _login(self) -> None:
        """Authenticate with qBittorrent and store the session cookie."""
        response = self._handler.post(
            endpoint='api/v2/auth/login',
            data={
                'username': self.cfg('username'),
                'password': self.cfg('password', default=''),
            },
            headers={**self._headers, **self.FORM_HEADERS},
        )
        login_data = response.data
        if response.status == 204 and login_data is None:
            login_data = 'Ok.'
        if (
            response.status not in {200, 204}
            or login_data != 'Ok.'
        ):
            raise ValueError(f"Failed to authenticate with qBittorrent: {response.status}")
        auth_cookies = self._response_cookies(response=response)
        session_cookie = self._session_cookie(cookies=auth_cookies)
        if not session_cookie:
            raise ValueError(f"Failed to authenticate with qBittorrent: {response.status}")
        self._sid = session_cookie
        self._auth_cookies = auth_cookies
        log("qBittorrent session cookie retrieved.")

    def _cookies(self) -> dict:
        """Return the current qBittorrent session cookies."""
        return self._auth_cookies.copy()

    def _referer(self) -> str:
        """Return a same-origin Referer value for qBittorrent WebAPI requests."""
        parsed = urlsplit(self._url)
        if not parsed.scheme or not parsed.netloc:
            return self._url.rstrip('/') + '/'
        path = parsed.path.rstrip('/') + '/' if parsed.path else '/'
        return urlunsplit((parsed.scheme, parsed.netloc, path, '', ''))

    def _origin(self) -> str:
        """Return a same-origin Origin value for qBittorrent WebAPI requests."""
        parsed = urlsplit(self._url)
        if not parsed.scheme or not parsed.netloc:
            return self._url.rstrip('/')
        return urlunsplit((parsed.scheme, parsed.netloc, '', '', ''))

    def _multipart_fields(self, data: dict) -> dict:
        """Return multipart form fields for qBittorrent torrent-add requests."""
        return {key: (None, str(value)) for key, value in data.items() if value is not None}

    def _response_cookies(self, response) -> dict:
        """Return response cookies from requests or raw Set-Cookie headers."""
        cookies = dict(response.cookies or {})
        cookie_header = response.headers.get('Set-Cookie') if response.headers else None
        if not cookie_header:
            return cookies
        cookie = SimpleCookie()
        cookie.load(cookie_header)
        for key, morsel in cookie.items():
            cookies[key] = morsel.value
        return cookies

    def _session_cookie(self, cookies: dict) -> str | None:
        """Return a qBittorrent session cookie value from known SID cookie names."""
        for key, value in cookies.items():
            if key == 'SID' or key.startswith('QBT_SID'):
                return value
        return None
