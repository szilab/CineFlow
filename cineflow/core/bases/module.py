"""Base class for API consumer clients."""

import copy
import time
from typing import List, Dict, Any
from abc import ABC, abstractmethod
from cineflow.core.logger import log
from cineflow.core.config import Config, cfg
from cineflow.core.schema import LIMIT
from cineflow.utils.misc import MEDIA_KINDS, sanitize_name
from cineflow.utils.request import RequestHandler
from cineflow.utils.torrent import folder_plan, join_path, media_folder, path_name, same_path
from cineflow.utils.directory import CleanupScheduler, DirectoryHandler
from cineflow.runtime import export_directory


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
        # the media kind comes from the flow that builds the module, never from config.yaml
        self.kind = (config or {}).get('kind', 'movie')

    def field_choices(self, source: str) -> list[str] | None:  # pylint: disable=unused-argument
        """Return the valid values of a field read from the service (``Field.choices``).

        None means the module offers no such list; service errors raise.
        """
        return None

    def cfg(self, key: str, default=None) -> dict:
        """Return a module setting; its environment variable overrides it."""
        definition = getattr(self, 'DEFINITION', None)
        spec = definition.field(key) if definition else None
        environment = spec.environment_name(self.name) if spec else None
        return Config.getfrom(self._cfg, key=key, module=self.name, default=default, environment=environment)

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

    # most items a 'get' action collects (config key 'limit')
    _limit = LIMIT.default
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
        self._limit = self.cfg('limit', LIMIT.default)
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
            return {'ok': True, 'message': 'Connected.'}
        if status == 0:
            return {'ok': False, 'message': 'Service is unreachable.'}
        if status in (401, 403):
            return {'ok': False, 'message': 'Authentication failed.'}
        return {'ok': False, 'message': f'Unexpected response (HTTP {status}).'}

    def match(self, results: List[Dict], media: dict) -> dict:
        """Match item from the results"""
        for item in results or []:
            if self._match_w_id(item=item, media=media):
                log(f"Item '{media.get('title')}' match found by TMDB ID")
                return item
            if self._match_w_id(item=item, media=media, idkey='imdbid'):
                log(f"Item '{media.get('title')}' match found by IMDB ID")
                return item
            if self._match_w_title(item=item, media=media):
                log(f"Item '{media.get('title')}' match found by title ID")
                return item
            if self._match_w_title(item=item, media=media, titlekey='alttitle'):
                log(f"Item '{media.get('title')}' match found by alternate title ID")
                return item
        return None

    def _match_w_id(self, item: dict, media: dict, idkey: str = 'tmdbid') -> bool:
        """Match item from the results"""
        if item.get(idkey) and media.get(idkey) and str(item.get(idkey)) == str(media.get(idkey)):
            return True
        return False

    def _match_w_title(self, item: dict, media: dict, titlekey: str = 'title') -> bool:
        """Match by title; the year must match too, except for series without a known year."""
        title = sanitize_name(name=media.get(titlekey)).lower()
        if not title:
            return False
        it = sanitize_name(name=item.get('title')).lower()
        ia = sanitize_name(name=item.get('alttitle')).lower()
        iy = str(item.get('year'))
        my = str(media.get('year'))
        # series releases often have no year; the title alone must match then
        year_unknown = self._kind == 'tv' and not (item.get('year') and media.get('year'))
        if not year_unknown and iy != my:
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
            local_match = self.search(media=item)
            if isinstance(local_match, list) and local_match:
                # several matches, e.g. the episode releases of a season: one item each
                for match in local_match:
                    to_return.append(self._update(original=copy.deepcopy(item), updates=match))
                log(f"Item '{item.get('title')}' ({item.get('year')}) extended {len(local_match)} times.")
            elif local_match:
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
        results = self._compare_items(query=query)
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

    def _compare_items(self, query: Any = None) -> List[dict] | None:
        """Return the items 'Not in' and 'Also in' compare with."""
        return self.get(query=query)

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
        """Collect media, at most ``limit`` items; ``isInverse`` returns the items outside the query."""
        results = self._collect(query=query)
        return None if results is None else results[:self._limit]

    def _compare_items(self, query: Any = None) -> List[dict] | None:
        """Compare with every matching item: a limit would hide items that are on the server."""
        return self._collect(query=query)

    def _collect(self, query: Any = None) -> List[dict] | None:
        """Return every item of the query; ``isInverse`` returns the items outside it."""
        input_items = query if isinstance(query, list) else []
        query = self._parse_query(query)
        results = None
        if query.get("isInverse"):
            del query["isInverse"]
            inverse_query = self._inverse_query(query)
            q_items = self._library_items(query=query)
            if q_items is not None:
                results = self._inverse_items(query_items=input_items or q_items, query=inverse_query)
        else:
            results = self._library_items(query=query)
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
            names = library if isinstance(library, list) else [library]
            for name in names:
                if name not in self._libraries():
                    raise ValueError(f"Library '{name}' not found in {self.__class__.__name__}.")
            keys = [self._libraries()[name] for name in names]
            query[self.LIBRARY_KEY] = keys if isinstance(library, list) else keys[0]
        return query

    def _library_items(self, query: dict) -> List[dict] | None:
        """Return the items of the query; a list of libraries is queried one by one."""
        keys = query.get(self.LIBRARY_KEY)
        if not isinstance(keys, list):
            return self._get_items(query=query)
        results = []
        for key in keys:
            items = self._get_items(query={**query, self.LIBRARY_KEY: key})
            if items is None:
                return None
            results.extend(items)
        return results

    def field_choices(self, source: str) -> list[str] | None:
        """Return the library names for library fields."""
        if source == 'libraries':
            return sorted(self._libraries())
        return super().field_choices(source)

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

    def _download_directory(self, media: dict) -> str | None:
        """Return the download directory of an item; ``kind_folder`` adds its media kind (movie or tv)."""
        directory = self.cfg('directory')
        if not directory or not self.cfg('kind_folder', default=False):
            return directory or None
        kind = media.get('kind') if media.get('kind') in ('movie', 'tv') else self._kind
        separator = '\\' if '\\' in directory and '/' not in directory else '/'
        return directory.rstrip('/\\') + separator + kind

    def search(self, media: dict) -> dict:
        """Search media for the given title in the torrent list."""
        results = self.get(query=sanitize_name(name=media.get('title')))
        if match := self.match(results=results, media=media):
            return match
        if media.get('alttitle'):
            results = self.get(query=sanitize_name(name=media.get('alttitle')))
            return self.match(results=results, media=media)
        return None

    def rename(self, data: List[Dict]) -> List[Dict]:
        """Give the download of each added torrent a Jellyfin folder: 'Title (year) [tmdbid-N]'.

        The root folder of the torrent is renamed; the content of a torrent without
        a root folder (a single file) moves into a new folder of that name, and so
        does a torrent whose folder name another download already uses (e.g. an
        other episode release of the series). Nothing changes when the torrent or
        its file list (metadata) is not available. ``<module>_folder`` records the
        outcome: renamed, moved, done, pending or error.
        """
        for media in data or []:
            if media.get(f'{self.name}_status') not in ('added', 'duplicate'):
                continue
            if not (target := media_folder(media, suffix=self.cfg('suffix', default='') or '')):
                log(f"Item '{media.get('title')}' has no title for a folder name.", level='WARNING')
                continue
            media[f'{self.name}_folder'] = self._name_folder(media=media, target=target)
        return data

    def delete(self, data: List[Dict]) -> List[Dict]:
        """Remove the torrent of each item from the client, optionally with its files.

        A torrent that is not found stays. Select the torrents in an earlier step
        (e.g. ``get`` with ``min_age``). ``<module>_deleted`` records the outcome:
        deleted, missing or error.
        """
        delete_files = bool(self.cfg('delete_files', default=False))
        for media, state in self._found_torrents(data=data):
            if state is None:
                media[f'{self.name}_deleted'] = 'missing'
            elif self._remove_torrent(state=state, delete_files=delete_files):
                log(f"Torrent of '{media.get('title')}' removed from {self.name}.", level='MSG')
                media[f'{self.name}_deleted'] = 'deleted'
            else:
                log(f"Failed to remove torrent of '{media.get('title')}' from {self.name}.", level='ERROR')
                media[f'{self.name}_deleted'] = 'error'
        return data

    def move(self, data: List[Dict]) -> List[Dict]:
        """Move the data of each item's torrent into the directory ``location``.

        ``<module>_moved`` records the outcome: moved, done, missing or error.
        """
        if not (location := str(self.cfg('location', default='') or '').strip()):
            log(f"No target location configured for {self.name} move.", level='ERROR')
            return data
        for media, state in self._found_torrents(data=data):
            if state is None:
                media[f'{self.name}_moved'] = 'missing'
            elif same_path(state['directory'], location):
                media[f'{self.name}_moved'] = 'done'
            elif self._move_content(state=state, location=location):
                log(f"Torrent of '{media.get('title')}' moved into '{location}'.", level='MSG')
                media[f'{self.name}_moved'] = 'moved'
            else:
                log(f"Failed to move torrent of '{media.get('title')}' into '{location}'.", level='ERROR')
                media[f'{self.name}_moved'] = 'error'
        return data

    def _found_torrents(self, data: List[Dict]):
        """Yield (item, torrent state) of the items; the state is None when the torrent is not found."""
        for media in data or []:
            if not (torrent_hash := self._torrent_hash(media=media)):
                log(f"Torrent of '{media.get('title')}' could not be identified, skipped.", level='WARNING')
                yield media, None
            elif not (state := self._torrent_state(torrent_hash=torrent_hash)):
                log(f"Torrent of '{media.get('title')}' not found in {self.name}, skipped.", level='WARNING')
                yield media, None
            else:
                yield media, state

    def _remove_torrent(self, state: dict, delete_files: bool) -> bool:
        """Remove a torrent from the client."""
        raise NotImplementedError

    def _name_folder(self, media: dict, target: str) -> str:
        """Give the download of one item the folder ``target``; return the outcome."""
        title = media.get('title')
        if not (torrent_hash := self._torrent_hash(media=media)):
            log(f"Torrent of '{title}' could not be identified, folder not renamed.", level='WARNING')
            return 'error'
        if not (state := self._torrent_state(torrent_hash=torrent_hash)):
            log(f"Torrent of '{title}' not found in {self.name}, folder not renamed.", level='WARNING')
            return 'error'
        action, root = folder_plan(state['files'], target)
        if action == 'wait':
            log(f"Torrent of '{title}' has no metadata yet, folder not renamed; wait longer before.",
                level='WARNING')
            return 'pending'
        directory = state['directory']
        if action == 'done' or path_name(directory) == target:
            return 'done'
        if action == 'rename':
            if (locations := self._torrent_locations()) is None:
                log(f"Torrents of {self.name} not available, folder of '{title}' not renamed.", level='WARNING')
                return 'error'
            folder = join_path(directory, target)
            if not any(same_path(content, folder) or same_path(location, folder) for location, content in locations):
                if self._rename_root(state=state, root=root, target=target):
                    log(f"Folder '{root}' renamed to '{target}'.", level='MSG')
                    return 'renamed'
                log(f"Failed to rename folder '{root}' to '{target}'.", level='ERROR')
                return 'error'
        location = join_path(directory, target)
        if self._move_content(state=state, location=location):
            log(f"Torrent of '{title}' moved into '{location}'.", level='MSG')
            return 'moved'
        log(f"Failed to move torrent of '{title}' into '{location}'.", level='ERROR')
        return 'error'

    def _torrent_hash(self, media: dict) -> str | None:
        """Return the info hash of the item's torrent."""
        return media.get('torrent_hash')

    def _torrent_state(self, torrent_hash: str) -> dict | None:
        """Return {'id', 'directory', 'files'} of a torrent; None when unavailable."""
        raise NotImplementedError

    def _torrent_locations(self) -> list[tuple[str, str]] | None:
        """Return the (download directory, content path) of every torrent; None on failure."""
        raise NotImplementedError

    def _rename_root(self, state: dict, root: str, target: str) -> bool:
        """Rename the root folder of a torrent on the disk."""
        raise NotImplementedError

    def _move_content(self, state: dict, location: str) -> bool:
        """Move the content of a torrent into the directory ``location``."""
        raise NotImplementedError

    def _map_torrents(self, items: list, query: Any = None) -> List[Dict]:
        """Map torrents and keep the ones the query selects.

        A text query keeps the torrents whose title contains it. A structured
        query may set ``min_age`` (hours): only torrents added at least that long
        ago stay; a torrent with an unknown add time never does.
        """
        title = query if isinstance(query, str) else ''
        min_age = self._min_age(query)
        results = []
        for item in items:
            media = self.map(item=item)
            if media and (not title or title in sanitize_name(name=media.get('title'))) \
                    and self._old_enough(media=media, min_age=min_age):
                results.append(media)
            else:
                log(f"Skipping item '{item.get('name')}' invalid or not match.", level='DEBUG')
        return results

    @staticmethod
    def _min_age(query: Any) -> float:
        """Return the ``min_age`` of a structured query in seconds."""
        try:
            return max(float(query.get('min_age') or 0), 0) * 3600 if isinstance(query, dict) else 0
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _old_enough(media: dict, min_age: float) -> bool:
        """Return whether the torrent was added at least ``min_age`` seconds ago."""
        if not min_age:
            return True
        try:
            return time.time() - float(media.get('added')) >= min_age
        except (TypeError, ValueError):
            return False


class LibraryBase(ModuleBase):
    """Library module base class."""

    def __init__(self, directory: str = None, config: dict = None, required: list = None) -> None:
        """Initialize the consumer module."""
        super().__init__(config=config, required=required)
        directory = directory or self.cfg('directory')
        self._handler = DirectoryHandler(directory=directory, root=export_directory(self.cfg('export_directory')))
        self._handler.max_item_count = self.cfg("limit", 500)
        self._handler.max_item_age = self.cfg("age", 120)
        CleanupScheduler.schedule(self._handler)
