"""Jackett API consumer module."""

from typing import List, Any
from cineflow.bases.module import ConsumerBase
from cineflow.system.misc import sort_data, sanitize_name, media_title, media_year


class Jackett(ConsumerBase):
    """
    Jackett API consumer module.

    Configuration:
        - url: Jackett base URL (e.g., http://localhost:9117/api/v2.0/indexers/all/results)
        - token: Jackett API key (required)
        - limit: Number of torrent results to return (default: 10)

    Functions:
        - get: Collet most recent torrents
        - search: Search torrents for a given title.
    """

    def __init__(self, config: dict = None) -> None:
        super().__init__(config=config, required=['url', 'token'])
        self.cache_time = 3600
        self._category = '2000' if self._kind == "movie" else '5000'
        self._data_mappings = {
            'title': ['Title'],
            'year': ['Title'],
            'link': ['Link'],
            'size': ['Size'],
            'torrent': ['Title'],
            'seeders': ['Seeders'],
        }
        self._data_transforms = {
            'title': media_title,
            'year': media_year,
        }

    def get(self, query: Any = None):
        """Collect torrents from Jackett."""
        results = self._get_results(query=query)
        return results[:self._limit] if results else []

    def search(self, title: str, year: int, tmdbid: str = None) -> List[dict]:  # pylint: disable=arguments-differ
        """Search torrents for the given title."""
        results = self._get_results(query=f"{sanitize_name(name=title)} {year}")
        return self.match(results=results, title=title, year=year)

    def _get_results(self, query: Any = None) -> List[dict]:
        if not query:
            query = ''
        query_include = self.cfg('include', default='')
        response = self._handler.get(
            endpoint="/api/v2.0/indexers/all/results",
            params={
                'apikey': self.cfg('token'),
                'Query': query if not query_include else f"{query} {query_include}",
                'Category[]': self._category,
            }
        )
        if not response.data or not isinstance(response.data, dict):
            return []
        results = []
        for item in sort_data(response.data.get('Results', []), param="Seeders", reverse=True):
            if media := self.map(item=item):
                results.append(media)
        return results
