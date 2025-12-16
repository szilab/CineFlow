"""Base class for API consumer clients."""

from typing import List, Dict, Any
from abc import ABC, abstractmethod
from cineflow.system.logger import log
from cineflow.system.config import Config, cfg
from cineflow.system.misc import sanitize_name
from cineflow.system.request import RequestHandler
from cineflow.system.directory import DirectoryHandler


class ModuleBase():
    """Consumer base class"""

    def __init__(self, config: dict = None, required: list = None) -> None:
        """Initialize the module."""
        self.name = self.__class__.__name__.lower()
        self._cfg = config or {}
        if cfg(key=self.name):
            self._cfg.update(cfg(key=self.name))
        self._data_mappings = {
            'title': ['title'],
            'year': ['year'],
        }
        self._empty_property_allowed = False
        self._data_transforms = {}
        for key in required or []:
            if self.cfg(key):
                continue
            raise ValueError(f"Missing required module config '{self.name}.{key}'")

    def cfg(self, key: str, default=None) -> dict:
        """Return the module configuration."""
        return Config.getfrom(self._cfg, key=key, module=self.name, default=default)

    def map(self, item: dict) -> dict:
        """Interpret the received item as the data structure."""
        data = self._map_props(item=item)
        # all items must have a title and year
        if not data.get('title') or not data.get('year'):
            log(f"Item missing required fields: {item}")
            return {}
        # validate empty properties
        if not self._empty_property_allowed:
            for key, value in data.items():
                if value is None:
                    log(f"Empty property '{key}' not allowed in {self.name} module.")
                    return {}
        return data

    def _map_props(self, item: dict) -> dict:
        """Map the properties of the item to the data structure."""
        if not isinstance(item, dict):
            log(f"Invalid item type: {type(item)}. Expected dict.", level='WARNING')
            return {}
        data = {}
        for prop, aliases in self._data_mappings.items():
            # map the property if the name matches
            if prop in item:
                data[prop] = item[prop]
            else:
                # maps the property if the alias matches
                for alias in aliases:
                    if alias in item:
                        data[prop] = item[alias]
                        break
            # apply any data transformations
            if prop in self._data_transforms and data.get(prop):
                prop_val = self._data_transforms[prop](data[prop])
                data[prop] = prop_val
        return data

    @property
    def mappings(self) -> Dict:
        return self._data_mappings

    @mappings.setter
    def mappings(self, value: Dict) -> None:
        self._data_mappings = value

    @property
    def transforms(self) -> Dict:
        return self._data_transforms

    @transforms.setter
    def transforms(self, value: Dict) -> None:
        self._data_transforms = value

    @property
    def empty_property_allowed(self) -> bool:
        return self._empty_property_allowed

    @empty_property_allowed.setter
    def empty_property_allowed(self, value: bool) -> None:
        self._empty_property_allowed = value


class ConsumerBase(ModuleBase, ABC):
    """Consumer module base class."""

    def __init__(self, url: str = None, config: dict = None, required: list = None) -> None:
        """Initialize the consumer module."""
        super().__init__(config=config, required=required)
        self._url = url or self.cfg('url')
        if not self._url:
            raise ValueError(f"Missing required module config '{self.name}.url'")
        self._handler = RequestHandler(url=self._url)
        self._kind = 'movie'
        self._limit = self.cfg('limit', 100)
        self._force_upd_fields = []

    @abstractmethod
    def get(self, query: Any = None) -> List[dict]:
        """Search media for the given query."""

    @abstractmethod
    def search(self, title: str, year: int, alttitle: str = None, tmdbid: str = None) -> List[dict]:
        """Search media for the given title and year."""

    def match(
        self, results: List[Dict], title: str, year: int, alttitle: str = None
    ) -> dict:
        """Match item from the results by title and year."""
        title = sanitize_name(name=title).lower()
        if alttitle:
            alttitle = sanitize_name(name=alttitle).lower()
        if (
            self.cfg('quick_match') and
            len(results) == 1 and
            results[0].get('year') == str(year)
        ):
            return results[0]
        for item in results or []:
            if str(item.get('year')) == str(year):
                i_title = sanitize_name(name=item.get('title')).lower()
                i_alttitle = item.get('alttitle')
                if i_alttitle:
                    i_alttitle = sanitize_name(name=i_alttitle).lower()
                if i_title == title:
                    return item
                if alttitle and i_title == alttitle:
                    return item
                if i_alttitle and i_alttitle == title:
                    return item
                if alttitle and i_alttitle and i_alttitle == alttitle:
                    return item
        return None

    def enrich(self, data: list[dict]) -> List[Dict]:
        """Extend the received data with module properties"""
        to_return = []
        for item in data or []:
            if local_match := self.search(
                title=item.get('title'),
                year=item.get('year'),
                alttitle=item.get('alttitle'),
                tmdbid=item.get('tmdbid')
            ):
                self._update(original=item, updates=local_match)
                to_return.append(item)
                log(f"Item '{item.get('title')}' ({item.get('year')}) extended.")
            else:
                if not self.cfg('must_match', default=False):
                    to_return.append(item)
                log(f"No media found for '{item.get('title')}' ({item.get('year')})", level='MSG')
        return to_return

    def unique(self, data: list[dict], query: Any = None) -> List[Dict]:
        """Return items from the received data wich ones are not in the queried items"""
        return self._set_operations(data=data, query=query, operation='unique')

    def common(self, data: list[dict], query: Any = None) -> List[Dict]:
        """Return items from the received data which ones are in the queried items"""
        return self._set_operations(data=data, query=query, operation='common')

    def _set_operations(self, data: list[dict], query: Any = None, operation: str = 'common') -> List[Dict]:
        if not data:
            log("No data received for operation, empty list returned.")
            return []
        results = self.get(query=query)
        if not results:
            log("No results returned by the query, nothing to operate on.")
            return data
        to_return = []
        for d in data:
            match = False
            for r in results:
                if d.get('imdbid') and r.get('imdbid') and str(d.get('imdbid')) == str(r.get('imdbid')):
                    match = True
                    log(f"Item '{d.get('title')}' ({d.get('year')}) [{d.get('imdbid')}] is match on {operation}.")
                    break
                if d.get('tmdbid') and r.get('tmdbid') and str(d.get('tmdbid')) == str(r.get('tmdbid')):
                    match = True
                    log(f"Item '{d.get('title')}' ({d.get('year')}) [{d.get('tmdbid')}] is match on {operation}.")
                    break
                if d.get('title') == r.get('title') and d.get('year') == r.get('year'):
                    match = True
                    log(f"Item '{d.get('title')}' ({d.get('year')}) is match on {operation}.")
                    break
            if (operation == 'common' and match) or (operation == 'unique' and not match):
                to_return.append(d)
        log(f"Returning {len(to_return)} items after {operation} operation.")
        return to_return

    def _update(self, original: dict, updates: dict) -> dict:
        """Update the original dictionary with the updates."""
        for key, value in updates.items():
            if key not in original or key in self._force_upd_fields:
                original[key] = value
        return original

    @property
    def kind(self) -> str:
        return self._kind

    @kind.setter
    def kind(self, value: str) -> None:
        if not value and value not in ['movie', 'tv']:
            raise ValueError("Kind must be either 'movie' or 'tv'.")
        self._kind = value

    @property
    def cache_time(self) -> int:
        return self._handler.cache_time

    @cache_time.setter
    def cache_time(self, value: int) -> None:
        self._handler.cache_time = value

    @property
    def headers(self) -> dict:
        return self._handler.headers

    @headers.setter
    def headers(self, value: dict) -> None:
        self._handler.headers = value

    @property
    def params(self) -> dict:
        return self._handler.params

    @params.setter
    def params(self, value: dict) -> None:
        self._handler.params = value

    @property
    def rate_limit(self) -> float:
        return self._handler.rate_limit

    @rate_limit.setter
    def rate_limit(self, value: float) -> None:
        self._handler.rate_limit = value

    @property
    def limit(self) -> int:
        return self._limit

    @limit.setter
    def get_limit(self, value: int) -> None:
        self._limit = max(value, 10)


class LibraryBase(ModuleBase):
    """Library module base class."""

    def __init__(self, directory: str = None, config: dict = None, required: list = None) -> None:
        """Initialize the consumer module."""
        super().__init__(config=config, required=required)
        directory = directory or self.cfg('directory')
        self._handler = DirectoryHandler(directory=directory)
        self._handler.max_item_count = self.cfg("limit", 500)
        self._handler.max_item_age = self.cfg("age", 120)
