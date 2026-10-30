"""Base class for API consumer clients."""

import copy
from typing import List, Dict, Any
from abc import ABC, abstractmethod
from cineflow.core.logger import log
from cineflow.core.config import Config, cfg
from cineflow.utils.misc import MEDIA_KINDS, sanitize_name
from cineflow.utils.request import RequestHandler
from cineflow.utils.directory import CleanupScheduler, DirectoryHandler


def _merge_config(base: dict, override: dict) -> dict:
    """Return a recursive configuration merge without mutating either input."""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_config(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


class ModuleBase():
    """Consumer base class"""

    _kind = 'movie'

    def __init__(self, config: dict = None, required: list = None) -> None:
        """Initialize the module."""
        self.name = self.__class__.__name__.lower()
        global_config = cfg(key=self.name) or {}
        self._cfg = _merge_config(global_config, config or {})
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
        self._kind = 'movie'
        self.kind = self.cfg('kind', default='movie')

    def cfg(self, key: str, default=None) -> dict:
        """Return the module configuration."""
        return Config.getfrom(self._cfg, key=key, module=self.name, default=default)

    def map(self, item: dict) -> dict:
        """Interpret the received item as the data structure.

        Only title and year are mandatory; series release names often carry no
        year, so for ``kind: tv`` only the title is. Optional properties without
        a value are left out, so a later flow step (for example ``enrich``) can
        fill them.
        """
        data = self._map_props(item=item)
        if not data.get('title') or (self._kind != 'tv' and not data.get('year')):
            log(f"Item missing required fields: {item}")
            return {}
        if not self._empty_property_allowed:
            for key in [key for key, value in data.items() if value is None]:
                log(f"Empty property '{key}' omitted in {self.name} module.")
                del data[key]
        return data

    def _map_props(self, item: dict) -> dict:
        """Map the properties of the item to the data structure."""
        if not isinstance(item, dict):
            log(f"Invalid item type: {type(item)}. Expected dict.", level='WARNING')
            return {}
        data = {}
        for prop, aliases in self._data_mappings.items():
            # the property name wins, then the first alias that carries a value
            candidates = [key for key in (prop, *aliases) if key in item]
            if not candidates:
                continue
            key = next((key for key in candidates if item[key] is not None), candidates[0])
            data[prop] = item[key]
            # apply any data transformations
            if prop in self._data_transforms and data.get(prop):
                data[prop] = self._data_transforms[prop](data[prop])
        return data

    @property
    def kind(self) -> str:
        """Media kind handled by the module: 'movie' or 'tv'."""
        return self._kind

    @kind.setter
    def kind(self, value: str) -> None:
        if value not in MEDIA_KINDS:
            raise ValueError("Kind must be either 'movie' or 'tv'.")
        self._kind = value

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

    # cheap authenticated request used by the connection test
    CHECK_ENDPOINT = ''
    CHECK_PARAMS: dict = {}

    def __init__(self, url: str = None, config: dict = None, required: list = None) -> None:
        """Initialize the consumer module."""
        super().__init__(config=config, required=required)
        self._url = url or self.cfg('url')
        if not self._url:
            raise ValueError(f"Missing required module config '{self.name}.url'")
        self._handler = RequestHandler(url=self._url)
        self._limit = self.cfg('limit', 100)
        self._force_upd_fields = []

    @abstractmethod
    def get(self, query: Any = None) -> List[dict]:
        """Search media for the given query."""

    @abstractmethod
    def search(self, media: dict) -> dict:
        """Search media for the given title and year."""

    def check_connection(self) -> dict:
        """Test the service connection and credentials without using the cache."""
        if not self.CHECK_ENDPOINT:
            return {'ok': False, 'message': 'Connection test is not supported.'}
        response = self._handler.get(
            endpoint=self.CHECK_ENDPOINT, params=dict(self.CHECK_PARAMS), cache_time=0,
        )
        return self._check_result(status=response.status)

    @staticmethod
    def _check_result(status: int) -> dict:
        """Describe a connection test HTTP status."""
        if 200 <= status < 300:
            return {'ok': True, 'message': f'Connected (HTTP {status}).'}
        if status == 0:
            return {'ok': False, 'message': 'Service is unreachable.'}
        if status in (401, 403):
            return {'ok': False, 'message': f'Authentication failed (HTTP {status}).'}
        return {'ok': False, 'message': f'Unexpected response (HTTP {status}).'}

    def match(self, results: List[Dict], media: dict) -> dict:
        """Match item from the results"""
        quck_match = self.cfg('quick_match', default=False) and results and len(results) == 1
        for item in results or []:
            if self._match_w_id(item=item, media=media):
                log(f"Item '{media.get('title')}' match found by TMDB ID")
                return item
            if self._match_w_id(item=item, media=media, idkey='imdbid'):
                log(f"Item '{media.get('title')}' match found by IMDB ID")
                return item
            if self._match_w_title(item=item, media=media, quick_match=quck_match):
                log(f"Item '{media.get('title')}' match found by title ID")
                return item
            if self._match_w_title(item=item, media=media, titlekey='alttitle', quick_match=quck_match):
                log(f"Item '{media.get('title')}' match found by alternate title ID")
                return item
        return None

    def _match_w_id(self, item: dict, media: dict, idkey: str = 'tmdbid') -> bool:
        """Match item from the results"""
        if item.get(idkey) and media.get(idkey) and str(item.get(idkey)) == str(media.get(idkey)):
            return True
        return False

    def _match_w_title(
        self, item: dict, media: dict, titlekey: str = 'title', quick_match: bool = False
    ) -> bool:
        """Match item from the results"""
        title = sanitize_name(name=media.get(titlekey)).lower()
        if not title:
            return False
        it = sanitize_name(name=item.get('title')).lower()
        ia = sanitize_name(name=item.get('alttitle')).lower()
        iy = str(item.get('year'))
        my = str(media.get('year'))
        # series releases often have no year; the title alone must match then
        year_unknown = self._kind == 'tv' and not (item.get('year') and media.get('year'))
        if not quick_match and not year_unknown:
            if iy != my:
                return False
        if it == title:
            return True
        if ia and ia == title:
            return True
        return False

    def enrich(self, data: list[dict]) -> List[Dict]:
        """Extend the received data with module properties"""
        to_return = []
        for item in data or []:
            if local_match := self.search(media=item):
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

    def exclude(self, data: list[dict], query: Any = None) -> List[Dict]:
        """Exclude items from the received data wich ones are in the query"""
        if not isinstance(query, dict):
            return data
        if query.get('imdb_ids'):
            data = [item for item in data if item.get('imdbid') not in query.get('imdb_ids')]
        if query.get('tmdb_ids'):
            data = [item for item in data if item.get('tmdbid') not in query.get('tmdb_ids')]
        return data

    def _set_operations(self, data: list[dict], query: Any = None, operation: str = 'common') -> List[Dict]:
        if not data:
            log("No data received for operation, empty list returned.")
            return []
        results = self.get(query=query)
        if results is None:
            log("Remote query failed, refusing to operate on local data.", level='WARNING')
            return []
        if not results:
            log("No results returned by the query, nothing to operate on.")
            return [] if operation == 'common' else data
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
                if d.get('title') == r.get('title') and str(d.get('year')) == str(r.get('year')):
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
    def limit(self, value: int) -> None:
        self._limit = max(value, 10)


class MediaServerBase(ConsumerBase, ABC):
    """Shared query and inverse logic of media server modules."""

    ID_KEY = ''         # mapped item ID used to de-duplicate results
    LIBRARY_KEY = ''    # server query key that selects one library

    def get(self, query: Any = None) -> List[dict] | None:
        """Collect media; ``isInverse`` returns the items outside the query."""
        input_items = query if isinstance(query, list) else []
        query = self._parse_query(query)
        results = None
        if query.get("isInverse"):
            del query["isInverse"]
            inverse_query = self._inverse_query(query)
            q_items = self._get_items(query=query)
            if q_items is not None:
                results = self._inverse_items(query_items=input_items or q_items, query=inverse_query)
        else:
            results = self._get_items(query=query)
        if results is None:
            return None
        return list({item[self.ID_KEY]: item for item in results if item.get(self.ID_KEY)}.values())

    def search(self, media: dict) -> dict:
        """Search media for the given title."""
        return self.match(results=self._get_items(), media=media)

    def _parse_query(self, query: Any) -> dict:
        """Normalize a step query and resolve ``parentLibrary`` to the server key."""
        if not query or isinstance(query, list):
            return {}
        if isinstance(query, str):
            return {"searchTerm": query}
        if not isinstance(query, dict):
            raise ValueError(f"{self.__class__.__name__} 'query' must be a string or a dictionary.")
        query = dict(query)
        if library := query.pop("parentLibrary", None):
            if library not in self._libraries():
                raise ValueError(f"Library '{library}' not found in {self.__class__.__name__}.")
            query[self.LIBRARY_KEY] = self._libraries()[library]
        return query

    def _inverse_query(self, query: dict) -> dict:  # pylint: disable=unused-argument
        """Return the query that selects the full library for an inverse result."""
        return {}

    @abstractmethod
    def _libraries(self) -> dict:
        """Return the server libraries by name."""

    @abstractmethod
    def _get_items(self, query: dict = None) -> List[dict] | None:
        """Return the mapped items matching the query, or None on failure."""

    @abstractmethod
    def _inverse_items(self, query_items: List[dict], query: dict = None) -> List[dict] | None:
        """Return the library items that are not in the query items."""


class TorrentClientBase(ConsumerBase, ABC):
    """Shared behavior of download client modules."""

    def search(self, media: dict) -> dict:
        """Search media for the given title in the torrent list."""
        results = self.get(query=sanitize_name(name=media.get('title')))
        if match := self.match(results=results, media=media):
            return match
        if media.get('alttitle'):
            results = self.get(query=sanitize_name(name=media.get('alttitle')))
            return self.match(results=results, media=media)
        return None

    def _map_torrents(self, items: list, query: Any = None) -> List[Dict]:
        """Map torrents and keep the ones whose title contains the query."""
        results = []
        for item in items:
            media = self.map(item=item)
            if media and (not query or query in sanitize_name(name=media.get('title'))):
                results.append(media)
            else:
                log(f"Skipping item '{item.get('name')}' invalid or not match.", level='DEBUG')
        return results


class LibraryBase(ModuleBase):
    """Library module base class."""

    def __init__(self, directory: str = None, config: dict = None, required: list = None) -> None:
        """Initialize the consumer module."""
        super().__init__(config=config, required=required)
        directory = directory or self.cfg('directory')
        self._handler = DirectoryHandler(directory=directory)
        self._handler.max_item_count = self.cfg("limit", 500)
        self._handler.max_item_age = self.cfg("age", 120)
        CleanupScheduler.schedule(self._handler)
