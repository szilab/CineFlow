"""Transmission API consumer module."""

import base64
from typing import List, Dict, Any
import requests
from cineflow.core.bases.module import ConsumerBase
from cineflow.core.logger import log
from cineflow.utils.misc import sanitize_name, media_title, media_year


class Transmission(ConsumerBase):
    """
    Transmission API consumer module.

    Configuration:
        - url: Transmission base URL (e.g., http://localhost:9091/transmission/rpc)
        - username: Transmission username (optional)
        - password: Transmission password (optional)
    """

    def __init__(self, config: dict = None) -> None:
        super().__init__(config=config)
        self.cache_time = 0
        self._handler.ok_statuses = {200, 201, 202, 204, 409}
        username = self.cfg('username', default=None)
        password = self.cfg('password', default=None)
        self._auth = (username, password) if username else None
        self._session_id = self._get_session_id()
        self._data_mappings = {
            'title': ['name'],
            'year': ['name'],
            'status': ['status'],
            'percent_done': ['percentDone'],
        }
        self._data_transforms = {
            'title': media_title,
            'year': media_year,
        }

    def get(self, query: Any = None) -> List[Dict]:
        """Get torrents from the Transmission API."""
        fields = ['id', 'name', 'status', 'percentDone', 'totalSize']
        data = self._rpc_request(method='torrent-get', params={'fields': fields})
        if data.get('torrents'):
            data = data['torrents']
        else:
            log("No torrents found or invalid response from Transmission API.", level='WARNING')
            return []
        results = []
        for item in data:
            if media := self.map(item=item):
                if media and query and query in media.get('title'):
                    results.append(media)
                elif media and not query:
                    results.append(media)
                else:
                    log(f"Skipping item '{item.get('name')}' invalid or not match.", level='DEBUG')
        return results

    def search(self, media: dict) -> dict:  # pylint: disable=arguments-differ
        """Search media for the given title in torrent list."""
        results = self.get(query=sanitize_name(name=media.get('title')))
        if match := self.match(results=results, media=media):
            return match
        if media.get('alttitle'):
            results = self.get(query=sanitize_name(name=media.get('alttitle')))
            return self.match(results=results, media=media)
        return None

    def put(self, data: List[Dict]) -> List[Dict]:
        """Add torrent to the download list."""
        if not data:
            log("No data provided to add to Transmission.", level='MSG')
            return data
        for media in data:
            if params := self._prepare_params(media=media):
                response = self._rpc_request(method='torrent-add', params=params)
                self._handle_response(media=media, response=response)
        return data

    def _prepare_params(self, media: dict) -> dict:
        """Prepare the parameters for the torrent add request."""
        if not media.get('link'):
            log(f"Item '{media.get('title')}' is missing torrent link.", level='WARNING')
            return None

        params = {}
        if self.cfg('directory'):
            params['download-dir'] = self.cfg('directory')

        link = media['link']
        if link.startswith('magnet:'):
            params['filename'] = link
            return params

        if link.startswith(('http://', 'https://')):
            return self._download_torrent(link=link, params=params, media=media)

        log(f"Unsupported torrent link: {link}", level='ERROR')
        return None

    def _download_torrent(self, link: str, params: dict, media: dict) -> dict:
        """Download the torrent file from the link."""
        try:
            req = requests.get(link, timeout=30, allow_redirects=True, headers={'User-Agent': 'Transmission'})
            req.raise_for_status()
            if req.content.startswith(b'd8:announce'):
                params['metainfo'] = base64.b64encode(req.content).decode()
                return params
            log(f"Jackett link not a file (Content-Type={req.headers.get('Content-Type', '')})", level='ERROR')
            media['transmission_status'] = 'invalid_torrent'
        except requests.RequestException as exc:
            log(f"Failed to download torrent from Jackett: {exc}", level='ERROR')
            media['transmission_status'] = 'error'
        return None

    def _handle_response(self, media: dict, response: dict) -> None:
        """Handle the response from the Transmission API."""
        if response.get('torrent-duplicate'):
            log(f"Torrent '{media.get('title')}' already exists in Transmission.")
            media['transmission_status'] = 'duplicate'
        elif response.get('torrent-added'):
            log(f"Torrent '{media.get('title')}' added successfully.", level='MSG')
            media['transmission_status'] = 'added'
        else:
            log(f"Failed to add torrent '{media.get('title')}': {response.get('result')}", level='ERROR')
            media['transmission_status'] = 'error'

    def _rpc_request(self, method: str, params: dict = None) -> dict:
        """Make a request to the Transmission RPC API."""
        response = self._handler.post(
            endpoint=self.cfg('rpc_path', default='transmission/rpc'),
            data=None,
            json={'method': method, 'arguments': params or {}},
            headers={
                'X-Transmission-Session-Id': self._session_id
            },
            auth=self._auth
        )
        # Handle session ID refresh if needed
        if response.status == 409:
            self._session_id = self._get_session_id()
            return self._rpc_request(method=method, params=params)
        if not response.data or not isinstance(response.data, dict):
            log(f"Invalid response from Transmission API: {response.status}, {response.data}", level='WARNING')
            return {}

        arguments = response.data.get('arguments') or {}
        if isinstance(arguments, dict):
            arguments['result'] = response.data.get('result')
        return arguments

    def _get_session_id(self) -> str:
        """Get the session ID from the Transmission API."""
        response = self._handler.post(
            endpoint=self.cfg('rpc_path', default='transmission/rpc'),
            data=None,
            json={'method': 'session-set'},
            auth=self._auth
        )
        session_id = response.headers.get('X-Transmission-Session-Id')
        if not session_id:
            raise ValueError(f"Failed to get session ID: {response.status}")
        log("Transmission session ID retrieved.")
        return session_id
