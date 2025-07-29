"""Transmission API consumer module."""

from typing import List, Dict, Any
from cineflow.bases.module import ConsumerBase
from cineflow.system.logger import log
from cineflow.system.misc import sanitize_name, media_title, media_year


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

    def search(self, title: str, year: int) -> List[dict]:  # pylint: disable=arguments-differ
        """Search media for the given title in torrent list."""
        results = self.get(query=f"{sanitize_name(name=title)} {year}")
        return self.match(results=results, title=title, year=year)

    def put(self, data: List[Dict]) -> List[Dict]:
        """Add torrent to the download list."""
        if not data:
            log("No data provided to add to Transmission.", level='MSG')
            return data
        for media in data:
            if not media.get('link'):
                log(f"Item '{media.get('title')}' is missing torrent link.", level='WARNING')
                continue
            response = self._rpc_request(
                method='torrent-add',
                params={
                    'filename': media['link'],
                    **({'download-dir': self.cfg('directory')} if self.cfg('directory') else {})
                }
            )
            if response.get('torrent-duplicate'):
                log(f"Torrent '{media.get('title')}' already exists in Transmission.")
                media['transmission_status'] = 'duplicate'
            elif response.get('torrent-added'):
                log(f"Torrent '{media.get('title')}' added successfully.", level='MSG')
                media['transmission_status'] = 'added'
            else:
                log(f"Failed to add torrent '{media.get('title')}': {response.get('result')}", level='ERROR')
                media['transmission_status'] = 'error'
        return data

    def _rpc_request(self, method: str, params: dict = None) -> dict:
        """Make a request to the Transmission RPC API."""
        response = self._handler.post(
            endpoint=self.cfg('rpc_path', default='transmission/rpc'),
            data={},
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
        if not response.data or not response.data.get('arguments'):
            log(f"Invalid response from Transmission API: {response.status}", level='WARNING')
            return {}
        return response.data.get('arguments')

    def _get_session_id(self) -> str:
        """Get the session ID from the Transmission API."""
        response = self._handler.post(
            endpoint=self.cfg('rpc_path', default='transmission/rpc'),
            data={'method': 'session-set'},
            auth=self._auth
        )
        if not response.headers.get('X-Transmission-Session-Id'):
            raise ValueError(f"Failed to get session ID: {response.status}")
        log("Transmission session ID retrieved.")
        return response.headers.get('X-Transmission-Session-Id')
