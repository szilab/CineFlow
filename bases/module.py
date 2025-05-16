"""Base class for API consumer clients."""

import os
from typing import List, Dict
from system.logger import log
from system.config import cfg
from system.request import RequestHandler
from system.directory import DirectoryHandler
from system.database import Database


class ModuleBase():
    """Consumer base class"""

    def __init__(self, config: dict = {}) -> None:  # pylint: disable=dangerous-default-value
        """Initialize the module."""
        self.name = self.__class__.__name__.lower()
        self._cfg = {**cfg(key=self.name, default={}), **config}
        self._req_module_cfgs = []
        self._ready = False

    def ready(self) -> bool:
        """Check if the module is ready or not."""
        self._ready = True
        for key in self._req_module_cfgs:
            if self._cfg.get(key) is None:
                log(f"Missing module config '{self.name}.{key}'", level="WARNING")
                self._ready = False

    def get(self, data: list) -> List[Dict]:  # pylint: disable=useless-return,unused-argument
        """"Task to be executed by the module."""
        log(f"The 'get' function is not implemented for {self.name}.", level="WARNING")
        return None

    def put(self, data: list) -> None:  # pylint: disable=useless-return,unused-argument
        """"Task to be executed by the module."""
        log(f"The 'put' function is not implemented for {self.name}.", level="WARNING")
        return None

    def search(self, title: str, year: int) -> Dict:  # pylint: disable=unused-argument,useless-return
        """Search for item in the module source."""
        log(f"The 'search' function is not implemented for {self.name}.", level="WARNING")
        return None


class ConsumerBase(ModuleBase):
    """Consumer module base class."""

    def __init__(self, url: str, config: dict = {}) -> None:  # pylint: disable=dangerous-default-value
        """Initialize the consumer module."""
        super().__init__(config=config)
        self._handler = RequestHandler(url=url)
        self._limit = self._cfg.get("limit", 20)
        self._kind = self._cfg.get("kind", "movie")

    def consumer_get(self) -> List[Dict]:  # pylint: disable=useless-return
        """Collect media from the server."""
        log(
            f"The module '{self.name}' paritally implemented and not able to collect data!",
            level="WARNING"
        )
        return None

    def consumer_put(self) -> List[Dict]:  # pylint: disable=useless-return
        """Push media to the server."""
        log(
            f"The module '{self.name}' paritally implemented and not able to push data!",
            level="WARNING"
        )
        return None

    def consumer_search(self, title: str, year: int, kind: str) -> Dict:  # pylint: disable=unused-argument,useless-return
        """Search for item in the server."""
        log(
            f"The module '{self.name}' paritally implemented and not able to search data!",
            level="WARNING"
        )
        return None

    def _get_cache(self, title: str, year: int, kind: str) -> Dict:
        log(f"Getting cached data for '{title}' ({year})", level="DEBUG")
        return Database().get_media(source=self.name, title=title, year=year, kind=kind)

    def _set_cache(self, data: Dict) -> None:
        log(f"Setting cached data for '{data.title}' ({data.year})", level="DEBUG")
        Database().store_media(source=self.name, data=data)

    def _match(
            self, results: List[Dict], title: str, year: int, kind: str
        ) -> dict:
        """Match the results by title and year."""
        for item in results or []:
            if (
                item.get('kind') == kind and
                item.get('year') == year and
                item.get('title').lower() == title.lower()
            ):
                return item
        return None


class LibraryBase(ModuleBase):
    """Library module base class."""

    def __init__(self, config: dict = {}) -> None:  # pylint: disable=dangerous-default-value
        """Initialize the consumer module."""
        super().__init__(config=config)
        self._handler = None
        self._limit = self._cfg.get("limit", 50)
        self._req_module_cfgs = ['path']

    def ready(self) -> None:
        """Check if the module is ready."""
        super().ready()
        self._handler = DirectoryHandler(path=self._cfg.get('path'))
        self._ready = self._handler.usable()
        if not self._ready:
            log(f"Library path '{self._cfg.get('path')}' is not usable.", level='WARNING')

    def cleanup(self) -> None:
        """Cleanup the library."""
        self.ready()
        if not self._ready:
            return
        detailed = [{'p': item, 'c': os.path.getctime(item)} for item in self._handler.all()]
        detailed.sort(key=lambda x: x['c'], reverse=True)
        for item in detailed[self._limit:]:
            self._handler.remove(item['p'])
