"""Plex API consumer module."""

from typing import List
from cineflow.core.logger import log
from cineflow.core.bases.module import MediaServerBase
from cineflow.core.schema import (
    ModuleDefinition, Field, LIMIT, MEDIA_SERVER_QUERY, consumer_actions,
)
from cineflow.utils.misc import fix_imdbid


class Plex(MediaServerBase):
    """
    Plex API consumer module.

    Configuration:
        - url: Plex base URL (e.g., http://localhost:32400)
        - token: Plex authentication token (required)

    Functions:
        - get: Collect media from Plex.
        - search: Search media for a given title.
    """

    ID_KEY = 'plexid'
    LIBRARY_KEY = 'sectionKey'
    CHECK_ENDPOINT = '/library/sections'
    DEFINITION = ModuleDefinition(
        id='plex', label='Plex', category='media server', connection_test=True,
        description="Plex media server libraries.",
        fields=(
            Field('url', 'url', 'URL', "Plex base URL, e.g. http://plex:32400.", required=True),
            Field('token', 'secret', 'Token', "Plex authentication token.", required=True),
            LIMIT,
            Field('ignore.libraries', 'list', 'Ignored libraries', "Library names left out of queries.",
                  advanced=True),
        ),
        actions=consumer_actions('Plex', query=(
            *MEDIA_SERVER_QUERY,
        )),
    )

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
        # libraries are loaded on first use, not at construction time
        self._library_list = None

    def _libraries(self) -> dict:
        """Return the Plex libraries, loading them on first use."""
        if self._library_list is None:
            self._library_list = self._get_libraries()
        return self._library_list

    def _get_items(self, query: dict = None) -> List[dict] | None:
        query = query or {}
        if query.get("searchTerm"):
            calls = [("/search", {"query": query["searchTerm"]}, "search")]
        elif query.get("sectionKey"):
            calls = [(f"/library/sections/{query['sectionKey']}/all", {}, f"section {query['sectionKey']}")]
        else:
            calls = [
                (f"/library/sections/{key}/all", {}, f"library '{name}'")
                for name, key in self._libraries().items()
            ]
        results = []
        for endpoint, params, label in calls:
            if (metadata := self._metadata(endpoint=endpoint, params=params, label=label)) is None:
                return None
            results.extend(metadata)
        return [self.map(item=item) for item in results]

    def _metadata(self, endpoint: str, params: dict, label: str) -> list | None:
        """Return the metadata list of one Plex request, or None on failure."""
        params = {**params, "includeGuids": "1"}
        if self._kind:
            params["type"] = "1" if self._kind == "movie" else "2"
        response = self._handler.get(endpoint=endpoint, params=params)
        if response.status == 0 or response.status >= 400:
            log(f"Plex API error {response.status} for {label}", level="ERROR")
            return None
        if not response.data or not response.data.get('MediaContainer'):
            return []
        return response.data['MediaContainer'].get('Metadata', [])

    def _inverse_items(
        self, query_items: List[dict], query: dict = None  # pylint: disable=unused-argument
    ) -> List[dict] | None:
        if not query_items:
            log(
                "Query items are empty, skipping inverse calculation "
                "to prevent library wipeout.", level="WARNING")
            return []
        all_items = self._get_items(query={})
        if all_items is None:
            log("Failed to query the Plex library for inverse calculation.", level="ERROR")
            return None
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
        if response.status == 0 or response.status >= 400:
            raise ValueError(f"Failed to query Plex libraries: HTTP {response.status}")
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
