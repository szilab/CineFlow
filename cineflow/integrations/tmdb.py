"""TMDB API consumer class"""

from typing import List, Any
from cineflow.core.logger import log
from cineflow.utils.misc import fix_imdbid
from cineflow.core.bases.module import ConsumerBase
from cineflow.core.schema import (
    ModuleDefinition, Field, LIMIT, consumer_actions,
)


class Tmdb(ConsumerBase):
    """
    TMDB API consumer module
    Configuration:
        - token: TMDB API token (required)
        - language: metadata language (default: en-US)
        - limit: safety cap of collected items (default: 200)

    Functions:
        - get: get media from TMDB API returns the list of media items
        - search: search for media in TMDB API return the matching item or None
    """

    # IMDb IDs of TMDb items never change, so their lookups can be kept for long.
    IMDB_CACHE_TIME = 30 * 86400
    CHECK_ENDPOINT = '/configuration'
    DEFINITION = ModuleDefinition(
        id='tmdb', label='TMDb', category='discovery', connection_test=True,
        description="The Movie Database: trending titles and metadata lookups.",
        fields=(
            Field('token', 'secret', 'API key', "TMDb API key (v3).", required=True),
            Field('language', 'string', 'Language', "Metadata language, e.g. en-US or hu-HU.",
                  default='en-US', step=True),
            LIMIT,
        ),
        actions=consumer_actions('TMDb'),
    )

    def __init__(self, config: dict = None) -> None:
        """Initialize the TMDB consumer."""
        super().__init__(url="https://api.themoviedb.org/3", config=config, required=['token'])
        self.cache_time = 10800
        self.mappings = {
            'title': ['title', 'name'],
            'alttitle': ['original_title', 'original_name'],
            'year': ['release_date', 'first_air_date'],
            'kind': ['media_type'],
            'tmdbid': ['id'],
            'poster': ['poster_path'],
            'imdbid': ['imdb_id'],
        }
        self.transforms = {
            "year": lambda x: str(x)[0:4],
            "poster": lambda x: f"https://image.tmdb.org/t/p/original{x}",
            "imdbid": fix_imdbid,
        }
        self.params = {
            'api_key': self.cfg('token'),
            'language': self.cfg('language', 'en-US'),
        }
        self._force_upd_fields = ['title']

    def get(self, query: Any = None) -> List[dict] | None:
        """Collect weekly trending media from the TMDB API."""
        collected = []
        page = 1
        while len(collected) < self.limit and page <= 20:
            response = self._handler.get(endpoint=f"/trending/{self.kind}/week", params={'page': page})
            results = self._results(response=response, label=f"collecting page {page}")
            if results is None:
                return None
            if not results:
                break
            for item in results:
                media = self.map(item=item)
                if media and (not query or query in media.get('title')):
                    collected.append(self._with_imdbid(media))
                    if len(collected) >= self.limit:
                        break
            page += 1
        log(f"Collected {len(collected)} items from TMDB.")
        return collected

    def search(self, media: dict) -> dict:
        """Search for media in TMDB."""
        if media.get('tmdbid'):
            if match := self.match(results=self._search_w_tmdbid(tmdbid=media['tmdbid']), media=media):
                return self._with_imdbid(match)
        elif media.get('imdbid'):
            if match := self.match(results=self._search_w_imdbid(imdbid=media['imdbid']), media=media):
                return self._with_imdbid(match)
        for titlekey in ('title', 'alttitle'):
            if titlekey == 'alttitle' and media.get('alttitle') == media.get('title'):
                break
            if match := self.match(results=self._search_w_title(media=media, titlekey=titlekey), media=media):
                return self._with_imdbid(match)
        return None

    @staticmethod
    def _results(response, label: str) -> list | None:
        """Return the result list of a TMDB list response, or None on failure."""
        if not 200 <= response.status < 300:
            log(f"TMDB API error {response.status} while {label}.", level="ERROR")
            return None
        if not isinstance(response.data, dict) or not isinstance(response.data.get('results'), list):
            log(f"Invalid TMDB response while {label}.", level="ERROR")
            return None
        return response.data['results']

    def _search_w_tmdbid(self, tmdbid: str) -> list[dict]:
        """Look up media by its TMDB ID."""
        response = self._handler.get(endpoint=f"/{self.kind}/{tmdbid}")
        if response.data and response.data.get('id'):
            return [media] if (media := self.map(item=response.data)) else []
        return []

    def _search_w_imdbid(self, imdbid: Any) -> list[dict]:
        """Look up media by its IMDb ID."""
        if not (number := fix_imdbid(imdbid)):
            return []
        response = self._handler.get(
            endpoint=f"/find/tt{number:07d}", params={'external_source': 'imdb_id'},
        )
        if not isinstance(response.data, dict):
            return []
        results = []
        for item in response.data.get(f"{self.kind}_results") or []:
            if media := self.map(item=item):
                # the item was found through this IMDb ID
                results.append({**media, 'imdbid': number})
        return results

    def _search_w_title(self, media: dict, titlekey: str) -> list[dict] | None:
        """Search for media by title."""
        if not media.get(titlekey) or len(media.get(titlekey)) < 2:
            return None
        response = self._handler.get(endpoint=f"/search/{self.kind}", params={'query': media.get(titlekey)})
        if response.data and response.data.get('results'):
            return [item for item in map(self.map, response.data['results']) if item]
        return None

    def _with_imdbid(self, media: dict) -> dict:
        """Add the IMDb ID to a selected item when TMDB did not include it."""
        if not media.get('imdbid') and media.get('tmdbid'):
            if imdbid := self._get_imdbid(tmdb_id=media['tmdbid']):
                media['imdbid'] = imdbid
        return media

    def _get_imdbid(self, tmdb_id: Any) -> int | None:
        """Look up the IMDb ID of a TMDB item."""
        response = self._handler.get(
            endpoint=f"/{self.kind}/{tmdb_id}/external_ids", cache_time=self.IMDB_CACHE_TIME,
        )
        if isinstance(response.data, dict) and response.data.get('imdb_id'):
            return fix_imdbid(response.data['imdb_id'])
        return None
