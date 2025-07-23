"""Transmission API consumer module."""
from typing import List, Dict
from requests.auth import HTTPBasicAuth
from system.logger import log
from bases.module import ConsumerBase, requires_ready


class Transmission(ConsumerBase):
    """
    Transmission API consumer module.

    Configuration:
        - url: Transmission base URL (e.g., http://localhost:9091/transmission/rpc)
        - username: Transmission username (optional)
        - password: Transmission password (optional)
    """

    def __init__(self, config: dict = None) -> None:
        super().__init__(config=config, rate_limit=0.5, cache_time=3600)
        self._def_module_cfgs = {
            'host': 'http://localhost:9091',
            'path': 'transmission/rpc',
        }
        if not self._cfg.get('url'):
            self._cfg['url'] = f"{self._cfg.get('host')}/{self._cfg.get('path')}"
        self._data_mappings = {
            'title': ['Title']
        }
        self._data_transforms = {}
        self.auth = None
        self.session_id = None

    def is_ready(self) -> None:
        """Check if the Transmission reachable."""
        super().is_ready()
        if self._cfg.get('username') and self._cfg.get('password'):
            self.auth = (self._cfg.get('username'), self._cfg.get('password'))

    @requires_ready
    def search(self, title: str, year: int, tmdbid: str = None) -> List[dict]:
        """Search media for the given title in torrent list."""

    @requires_ready
    def put(self, data: List[Dict]) -> None:
        """Add torrent to the download list."""

    def _update_session_id(self):
        response = self._handler.post(
            endpoint="",
            data={'method': 'session-get'},
            auth=self.auth,
        )
        pass
        # if response.status_code == 409:
        #     self.session_id = response.headers['X-Transmission-Session-Id']
        # else:
        #     response.raise_for_status()