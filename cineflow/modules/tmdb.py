"""TMDB API consumer class"""

from typing import List, Any
from cineflow.system.logger import log
from cineflow.bases.module import ConsumerBase


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
            'title': ['original_title'],
            'year': ['release_date', 'first_air_date'],
            'kind': ['media_type'],
            'tmdbid': ['id'],
            'poster': ['poster_path'],
        }
        self.transforms = {
            "year": lambda x: str(x)[0:4],
            "poster": lambda x: f"https://image.tmdb.org/t/p/original{x}",
        }
        self.params = {
            'api_key': self.cfg('token'),
            'language': self.cfg('language', 'en-US'),
        }

    def get(self, query: Any = None) -> List[dict]:
        """Collect media from the TMDB API."""
        collected = []
        page = 1
        while len(collected) < self.limit or page > 20:
            response = self._handler.get(
                endpoint=f"/trending/{self.kind}/week",
                params={'page': page, }
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

    def search(self, title: str, year: int, tmdbid: str = None) -> dict:
        """Search for media in TMDB."""
        if tmdbid:
            response = self._handler.get(
                endpoint=f"/{self.kind}/{tmdbid}",
                params={'append_to_response': 'images'}
            )
        else:
            response = self._handler.get(
                endpoint=f"/search/{self.kind}",
                params={'query': title, 'year': year}
            )
        if not response.data or not isinstance(response.data, dict):
            return None
        results = []
        for item in response.data.get('results', []):
            if media := self.map(item=item):
                results.append(media)
        return self.match(results=results, title=title, year=year)
