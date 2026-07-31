"""Plex API consumer module."""

from typing import List, Any
from cineflow.core.logger import log
from cineflow.core.bases.module import ConsumerBase
from cineflow.utils.misc import fix_imdbid


class Plex(ConsumerBase):
    """
    Plex API consumer module.

    Configuration:
        - url: Plex base URL (e.g., http://localhost:32400)
        - token: Plex authentication token (required)
        - limit: Number of results to return (default: 100)

    Functions:
        - get: Collect media from Plex.
        - search: Search media for a given title.
    """

    def __init__(self, config: dict = None) -> None:
        super().__init__(config=config, required=['url', 'token'])
        self.rate_limit = 0
        self.cache_time = 0
        self.mappings = {
            'title': ['title'],
            'alttitle': ['originalTitle'],
            'year': ['year'],
            'plexid': ['ratingKey'],
            'tmdbid': ['Guid'],
            'imdbid': ['Guid'],
        }
        self.transforms = {
            "tmdbid": lambda x: self._extract_guid(x, 'tmdb'),
            "imdbid": lambda x: fix_imdbid(self._extract_guid(x, 'imdb'))
        }
        self.headers = {
            "X-Plex-Token": self.cfg("token"),
            "Accept": "application/json"
        }
        self._library_list = self._get_libraries()

    def get(self, query: Any = None) -> List[dict] | None:
        """Collect media from Plex."""
        input_items = query if isinstance(query, list) else []
        query = self._parse_query(query)
        results = None
        if query.get("isInverse"):
            del query["isInverse"]
            q_items = self._get_items(query=query)
            if q_items is not None:
                results = self._inverse_items(query_items=input_items or q_items)
        else:
            results = self._get_items(query=query)
        if results is None:
            return None
        return list({
            item['plexid']: item for item in results if item.get('plexid')
        }.values())

    def search(self, media: dict) -> dict:
        """Search media for the given title."""
        results = self._get_items()
        return self.match(results=results, media=media)

    def _parse_query(self, query: Any) -> dict:
        if not query:
            return {}
        if isinstance(query, str):
            return {"searchTerm": query}
        if not isinstance(query, (dict, list)):
            raise ValueError("Plex 'query' must be a string or a dictionary.")
        if isinstance(query, dict):
            query = dict(query)
            if query.get("parentLibrary"):
                if query.get("parentLibrary") not in self._library_list:
                    raise ValueError(f"Library '{query['parentLibrary']}' not found in Plex.")
                query["sectionKey"] = self._library_list[query["parentLibrary"]]
                del query["parentLibrary"]
        return query

    def _get_items(self, query: dict = None) -> List[dict] | None:
        results = []
        query = query or {}
        
        # If searching by text
        if query.get("searchTerm"):
            params = {"query": query["searchTerm"]}
            if self._kind:
                params["type"] = "1" if self._kind == "movie" else "2"
            response = self._handler.get(
                endpoint="/search",
                params=params,
            )
            if response.status >= 400:
                log(f"Plex API error {response.status} for search: {params}", level="ERROR")
                return None
            if not response.data or not response.data.get('MediaContainer'):
                return []
            metadata = response.data.get('MediaContainer', {}).get('Metadata', [])
            results.extend(metadata)
        
        # If querying a specific library section
        elif query.get("sectionKey"):
            params = {}
            if self._kind:
                params["type"] = "1" if self._kind == "movie" else "2"
            response = self._handler.get(
                endpoint=f"/library/sections/{query['sectionKey']}/all",
                params=params,
            )
            if response.status >= 400:
                log(f"Plex API error {response.status} for section {query['sectionKey']}", level="ERROR")
                return None
            if not response.data or not response.data.get('MediaContainer'):
                return []
            metadata = response.data.get('MediaContainer', {}).get('Metadata', [])
            results.extend(metadata)
        
        # Otherwise, get all items from all libraries
        else:
            for lib_name, lib_key in self._library_list.items():
                params = {}
                if self._kind:
                    params["type"] = "1" if self._kind == "movie" else "2"
                response = self._handler.get(
                    endpoint=f"/library/sections/{lib_key}/all",
                    params=params,
                )
                if response.status >= 400:
                    log(f"Plex API error {response.status} for library '{lib_name}'", level="ERROR")
                    continue
                if not response.data or not response.data.get('MediaContainer'):
                    continue
                metadata = response.data.get('MediaContainer', {}).get('Metadata', [])
                results.extend(metadata)
        
        return [self.map(item=item) for item in results]

    def _inverse_items(self, query_items: List[dict]) -> List[dict]:
        if not query_items:
            log(
                "Query items are empty, skipping inverse calculation "
                "to prevent library wipeout.", level="WARNING")
            return []
        all_items = self._get_items(query={}) or []
        exclude_ids = set()
        for item in query_items:
            for key in ['plexid', 'tmdbid', 'imdbid']:
                if item.get(key):
                    exclude_ids.add(str(item[key]))
        not_in_query = []
        for item in all_items:
            found = False
            for key in ['plexid', 'tmdbid', 'imdbid']:
                if item.get(key) and str(item[key]) in exclude_ids:
                    found = True
                    break
            if not found:
                not_in_query.append(item)
        return not_in_query

    def _get_libraries(self) -> dict:
        response = self._handler.get(
            endpoint="/library/sections",
        )
        if not response.data or not response.data.get('MediaContainer'):
            raise ValueError("No libraries found in Plex, skip the rest.")
        
        directories = response.data.get('MediaContainer', {}).get('Directory', [])
        if not directories:
            raise ValueError("No libraries found in Plex, skip the rest.")
        
        library_list = {}
        for library in directories:
            if library.get("title") in self.cfg('ignore.libraries', []):
                log(f"Ignoring library '{library.get('title')}'.")
                continue
            library_list.update({
                library.get("title"): library.get("key"),
            })
        return library_list

    def _extract_guid(self, guid_list: List[dict], provider: str) -> str | None:
        """Extract provider ID from Plex Guid array."""
        if not guid_list or not isinstance(guid_list, list):
            return None
        
        for guid_obj in guid_list:
            if not isinstance(guid_obj, dict):
                continue
            guid_id = guid_obj.get('id', '')
            if guid_id.startswith(f"{provider}://"):
                return guid_id.replace(f"{provider}://", "")
        return None
