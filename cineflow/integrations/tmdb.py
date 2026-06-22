"""TMDB API consumer class"""

from typing import List, Any
from cineflow.core.logger import log
from cineflow.utils.misc import fix_imdbid
from cineflow.core.bases.module import ConsumerBase


class Tmdb(ConsumerBase):
    """
    TMDB API consumer module
    Configuration:
        - token: TMDB API token (required)
        - kind: media type: movie, tv (default: movie)
        - limit: number of items to collect (default: 20)
        - params: additional parameters for the API request (optional)

    Functions:
        - get: get media from TMDB API returns the list of media items
        - search: search for media in TMDB API return the matching item or None
    """

    def __init__(self, config: dict = None) -> None:
        """Initialize the TMDB consumer."""
        super().__init__(url="https://api.themoviedb.org/3", config=config, required=['token'])
        self.cache_time = 10800
        self.mappings = {
            'title': ['title'],
            'alttitle': ['original_title'],
            'year': ['release_date', 'first_air_date'],
            'kind': ['media_type'],
            'tmdbid': ['id'],
            'poster': ['poster_path'],
            'imdbid': ['imdb_id', 'id'],
        }
        self.transforms = {
            "year": lambda x: str(x)[0:4],
            "poster": lambda x: f"https://image.tmdb.org/t/p/original{x}",
            "imdbid": self._get_imdbid,
        }
        self.params = {
            'api_key': self.cfg('token'),
            'language': self.cfg('language', 'en-US'),
        }
        self._force_upd_fields = ['title']

    def get(self, query: Any = None) -> List[dict]:
        """Collect media from the TMDB API."""
        collected = []
        page = 1
        while len(collected) < self.limit or page > 20:
            response = self._handler.get(
                endpoint=f"/trending/{self.kind}",
                params={
                    'page': page, 'append_to_response': 'external_ids',
                    'with_watch_monetization_types': 'flatrate',
                    'watch_region': self.cfg('region', 'US'),
                }
            )
            if not response.data or not isinstance(response.data, dict):
                break
            for item in response.data.get('results', []):
                if media := self.map(item=item):
                    if media and query and query in media.get('title'):
                        collected.append(media)
                    elif media and not query:
                        collected.append(media)
                    if len(collected) >= self.limit:
                        break
            page += 1
        log(f"Collected {len(collected)} items from TMDB.")
        return collected

    def search(self, media: dict) -> dict:
        """Search for media in TMDB."""
        if match := self._match_w_result(media=media, tmdbid=media.get('tmdbid')):
            return match
        if media.get('alttitle') != media.get('title'):
            if match := self._match_w_result(media=media, titlekey='alttitle'):
                return match
        return None

    def _match_w_result(self, media: str, titlekey: str = 'title', tmdbid: str = None):
        if tmdbid:
            results = self._search_w_tmdbid(tmdbid=tmdbid)
            if match := self.match(results=results, media=media):
                return match
        results = self._search_w_title(media=media, titlekey=titlekey)
        return self.match(results=results, media=media)

    def _search_w_tmdbid(self, tmdbid: str) -> list[dict]:
        """Search for media in TMDB."""
        response = self._handler.get(
                endpoint=f"/{self.kind}/{tmdbid}",
                params={'append_to_response': 'images,external_ids'}
            )
        if response.data and response.data.get('id'):
            return self.map(item=response.data)
        return None

    def _search_w_title(self, media: dict, titlekey: str) -> list[dict]:
        """Search for media in TMDB."""
        if not media.get(titlekey) or len(media.get(titlekey)) < 2:
            return None
        response = self._handler.get(
            endpoint=f"/search/{self.kind}",
            params={'query': media.get(titlekey), 'append_to_response': 'images,external_ids'}
        )
        if response.data and response.data.get('results'):
            results = []
            for item in response.data.get('results'):
                if media := self.map(item=item):
                    results.append(media)
            return results
        return None

    def _get_imdbid(self, tmdb_id: str = None) -> str:
        tmdb_id = str(tmdb_id).strip()
        if not tmdb_id:
            return None
        if tmdb_id.startswith('tt'):
            return fix_imdbid(tmdb_id)
        response = self._handler.get(
            endpoint=f"/{self.kind}/{tmdb_id}",
        )
        if response.data and response.data.get('imdb_id'):
            return fix_imdbid(response.data.get('imdb_id'))
        return None
