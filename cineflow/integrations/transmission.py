"""Transmission API consumer module."""

import base64
from urllib.parse import urljoin
from typing import List, Dict, Any
import requests
from cineflow.core.bases.module import TorrentClientBase
from cineflow.core.schema import (
    ModuleDefinition, ActionDefinition, Field, LIMIT, INPUT_DATA, INPUT_QUERY, RENAME_FOLDERS,
    DELETE_TORRENTS, MOVE_TORRENTS, TORRENT_QUERY,
    consumer_actions,
)
from cineflow.core.logger import log
from cineflow.utils.misc import release_parsers
from cineflow.utils.torrent import join_path


class Transmission(TorrentClientBase):
    """
    Transmission API consumer module.

    Configuration:
        - url: Transmission base URL (e.g., http://localhost:9091/transmission/rpc)
        - username: Transmission username (optional)
        - password: Transmission password (optional)
    """

    MAX_REDIRECTS = 5
    DEFINITION = ModuleDefinition(
        id='transmission', label='Transmission', category='download client', connection_test=True,
        description="Transmission BitTorrent client.",
        fields=(
            Field('url', 'url', 'URL', "Transmission base URL, e.g. http://transmission:9091.",
                  required=True),
            Field('username', 'string', 'Username'),
            Field('password', 'secret', 'Password'),
            Field('directory', 'string', 'Download directory',
                  "Download directory on the client's machine.", step=True),
            Field('rpc_path', 'string', 'RPC path', default='transmission/rpc', advanced=True),
            LIMIT,
        ),
        actions=(
            ActionDefinition('get', 'Get torrents', "List the torrents of the client.",
                             input=INPUT_QUERY, query=TORRENT_QUERY, retrieval=True),
            ActionDefinition('put', 'Add torrents', "Add the item release links to the client.",
                             input=INPUT_DATA, side_effects=True),
            RENAME_FOLDERS,
            MOVE_TORRENTS,
            DELETE_TORRENTS,
            *consumer_actions('Transmission', query=TORRENT_QUERY)[1:4],
        ),
    )

    def __init__(self, config: dict = None) -> None:
        super().__init__(config=config)
        self.cache_time = 0
        self._handler.ok_statuses = {200, 201, 202, 204, 409}
        username = self.cfg('username', default=None)
        password = self.cfg('password', default=None)
        self._auth = (username, password) if username else None
        # the RPC session is opened on the first request, not at construction time
        self._session_id = None
        release_mappings, release_transforms = release_parsers(kind=self._kind, source='name', folder_names=True)
        self._data_mappings = {
            **release_mappings,
            'status': ['status'],
            'percent_done': ['percentDone'],
            'torrent_hash': ['hashString'],
            'added': ['addedDate'],
        }
        self._data_transforms = release_transforms

    def get(self, query: Any = None) -> List[Dict] | None:
        """Get torrents from the Transmission API."""
        fields = ['id', 'name', 'status', 'percentDone', 'totalSize', 'hashString', 'addedDate']
        data = self._rpc_request(method='torrent-get', params={'fields': fields})
        if data is None:
            log("Failed to retrieve torrents from Transmission API.", level='ERROR')
            return None
        if data.get('torrents'):
            data = data['torrents']
        else:
            log("No torrents found or invalid response from Transmission API.", level='WARNING')
            return []
        return self._map_torrents(items=data, query=query)[:self._limit]

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

    def check_connection(self) -> dict:
        """Test the RPC session and credentials."""
        try:
            self._session_id = self._get_session_id()
        except ValueError as exc:
            return {'ok': False, 'message': str(exc)}
        if self._rpc_request(method='session-get') is None:
            return {'ok': False, 'message': 'Transmission RPC request failed.'}
        return {'ok': True, 'message': 'Connected to Transmission RPC.'}

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
        """Download the torrent file, or use the magnet link it redirects to."""
        url = link
        try:
            for _ in range(self.MAX_REDIRECTS + 1):
                req = requests.get(
                    url, timeout=30, allow_redirects=False, headers={'User-Agent': 'Transmission'}
                )
                if req.is_redirect:
                    url = urljoin(url, req.headers.get('Location', ''))
                    if url.startswith('magnet:'):
                        params['filename'] = url
                        return params
                    continue
                req.raise_for_status()
                if req.content.startswith(b'd8:announce'):
                    params['metainfo'] = base64.b64encode(req.content).decode()
                    return params
                log(
                    f"Jackett link not a file (Content-Type={req.headers.get('Content-Type', '')})",
                    level='ERROR'
                )
                media['transmission_status'] = 'invalid_torrent'
                return None
            log(f"Too many redirects while downloading torrent for '{media.get('title')}'.", level='ERROR')
            media['transmission_status'] = 'error'
        except requests.RequestException as exc:
            log(f"Failed to download torrent from Jackett: {exc}", level='ERROR')
            media['transmission_status'] = 'error'
        return None

    def _handle_response(self, media: dict, response: dict | None) -> None:
        """Handle the response from the Transmission API."""
        response = response or {}
        torrent = response.get('torrent-added') or response.get('torrent-duplicate')
        if isinstance(torrent, dict) and torrent.get('hashString'):
            media['torrent_hash'] = torrent['hashString']
        if response.get('torrent-duplicate'):
            log(f"Torrent '{media.get('title')}' already exists in Transmission.")
            media['transmission_status'] = 'duplicate'
        elif response.get('torrent-added'):
            log(f"Torrent '{media.get('title')}' added successfully.", level='MSG')
            media['transmission_status'] = 'added'
        else:
            log(f"Failed to add torrent '{media.get('title')}': {response.get('result')}", level='ERROR')
            media['transmission_status'] = 'error'

    def _torrent_state(self, torrent_hash: str) -> dict | None:
        """Return the id, download directory and file names of a torrent."""
        data = self._rpc_request(
            method='torrent-get', params={'ids': [torrent_hash], 'fields': ['id', 'downloadDir', 'files']}
        )
        torrents = (data or {}).get('torrents')
        if not torrents or not isinstance(torrents[0], dict):
            return None
        torrent = torrents[0]
        return {
            'id': torrent.get('id'),
            'directory': torrent.get('downloadDir') or '',
            'files': [item.get('name') for item in torrent.get('files') or [] if isinstance(item, dict)],
        }

    def _torrent_locations(self) -> list[tuple[str, str]] | None:
        """Return the download directory and content path of every torrent."""
        data = self._rpc_request(method='torrent-get', params={'fields': ['name', 'downloadDir']})
        if data is None:
            return None
        return [
            (item.get('downloadDir') or '', join_path(item.get('downloadDir') or '', item.get('name') or ''))
            for item in data.get('torrents') or [] if isinstance(item, dict)
        ]

    def _rename_root(self, state: dict, root: str, target: str) -> bool:
        """Rename the root folder; Transmission renames the torrent with it."""
        params = {'ids': [state['id']], 'path': root, 'name': target}
        return self._rpc_request(method='torrent-rename-path', params=params) is not None

    def _remove_torrent(self, state: dict, delete_files: bool) -> bool:
        """Remove the torrent, with its data when ``delete_files``."""
        params = {'ids': [state['id']], 'delete-local-data': delete_files}
        return self._rpc_request(method='torrent-remove', params=params) is not None

    def _move_content(self, state: dict, location: str) -> bool:
        """Move the torrent data into ``location``."""
        params = {'ids': [state['id']], 'location': location, 'move': True}
        return self._rpc_request(method='torrent-set-location', params=params) is not None

    def _rpc_request(self, method: str, params: dict = None) -> dict | None:
        """Make a request to the Transmission RPC API."""
        if not self._session_id:
            self._session_id = self._get_session_id()
        for attempt in range(2):
            response = self._handler.post(
                endpoint=self.cfg('rpc_path', default='transmission/rpc'),
                data=None,
                json={'method': method, 'arguments': params or {}},
                headers={'X-Transmission-Session-Id': self._session_id},
                auth=self._auth
            )
            if response.status != 409:
                break
            if attempt == 0:
                self._session_id = self._get_session_id()
                continue
            log("Transmission session refresh failed after one RPC retry.", level='ERROR')
            return None
        if not response.data or not isinstance(response.data, dict):
            log(f"Invalid response from Transmission API: {response.status}, {response.data}", level='WARNING')
            return None

        result = response.data.get('result')
        if result != 'success':
            log(f"Transmission RPC '{method}' failed: {result}", level='ERROR')
            return None
        arguments = response.data.get('arguments') or {}
        if isinstance(arguments, dict):
            arguments['result'] = result
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
