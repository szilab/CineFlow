"""TMDB API consumer class"""

from typing import List, Dict
from system.config import cfg
from bases.data import MediaData
from bases.module import ConsumerBase


class TmdbData(MediaData):  # pylint: disable=too-few-public-methods
    """TMDB data."""

    def __init__(self, data: dict = {}, **kwargs) -> None:  # pylint: disable=dangerous-default-value
        super().__init__(data=data, **kwargs)
        self.data = {
            'poster': '',
            **self.data,
        }
        self._mappings = {
            'title': ['original_title', 'name'],
            'year': ['release_date', 'first_air_date'],
            'kind': ['media_type'],
            'poster': ['poster_path'],
        }
        self._transforms = {
            "year": lambda x: int(str(x)[0:4]),
            "poster": lambda x: f"https://image.tmdb.org/t/p/original{x}",
        }

class Tmdb(ConsumerBase):
    """
    TMDB API consumer module
    Configuration:
        - token: TMDB API token (required)
        - kind: media type: movie, tv (default: movie)
        - limit: number of items to collect (default: 20)
        - params: additional parameters for the API request (optional)

    Functions:
        - get: get media from TMDB API return list of media
        - search: search for media in TMDB API return the match or None
    """

    def __init__(self, config: dict = {}) -> None:  # pylint: disable=dangerous-default-value
        """Initialize the TMDB consumer."""
        super().__init__(url="https://api.themoviedb.org/3", config=config)
        self._req_module_cfgs = ['token']

    def ready(self) -> None:
        """Check if the TMDB module is ready."""
        super().ready()
        self._handler.params = {
            'api_key': self._cfg.get('token'),
            'language': cfg("language", default="en-US"),
        }

    def get(self, data: list = []) -> List[dict]:  # pylint: disable=dangerous-default-value
        """Collect media from the TMDB API."""
        self.ready()
        if not self._ready:
            return [*data]
        collected = []
        while len(collected) < self._limit:
            response = self._handler.get(
                endpoint=f"/trending/{self._kind}/week",
                params=self._cfg.get('params', {})
            )

            for item in response.data.get('results') or []:
                if media := TmdbData(kind=self._kind).map(item=item):
                    collected.append(media)
                    if len(collected) >= self._limit:
                        return collected
        return [*data, *collected]

    def search(self, title: str, year: int) -> Dict:
        """Search for media in TMDB."""
        self.ready()
        if not self._ready:
            return []
        response = self._handler.get(
            endpoint=f"/search/{self._kind}",
            params={'query': title, 'year': year}
        )
        if not response.data or not response.data.get('results'):
            return None
        results = [TmdbData(kind=self._kind).map(item=item) for item in response.data['results']]
        return self._match(results=results, title=title, year=year, kind=self._kind)
