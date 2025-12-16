"""Jackett API consumer module."""

from typing import List, Any
from cineflow.system.logger import log
from cineflow.system.misc import sort_data, fix_imdbid, sanitize_name, media_title, media_year, media_resolution
from cineflow.bases.module import ConsumerBase


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
            'resolution': ['Title', 'CategoryDesc'],
            'imdbid': ['Imdb'],
        }
        self._data_transforms = {
            'title': media_title,
            'year': media_year,
            'resolution': media_resolution,
            'imdbid': fix_imdbid,
        }
        self.params = {
            'apikey': self.cfg('token'),
        }

    def get(self, query: Any = None):
        """Collect torrents from Jackett."""
        results = self._get_results(query=query)
        return results[:self._limit] if results else []

    def search(self, title: str, year: int, alttitle: str = None, tmdbid: str = None) -> List[dict]:  # pylint: disable=arguments-differ
        """Search torrents for the given title."""
        query_pref = list(self.cfg('search_preference', default=[]))
        query_pref.append('')
        for q in query_pref:
            if match := self._sorted_match(title=title, year=year, alttitle=alttitle, query=q):
                return match
        return None

    def _sorted_match(self, title: str, year: int, alttitle: str = None, query: str = ''):
        results = self._search_w_query(title=title, year=year, query=query)
        if alttitle:
            r = self._search_w_query(title=alttitle, year=year, query=query)
            if r:
                results.extend(r)
        results = sort_data(results, param="seeders", reverse=True)
        return self.match(results=results, title=title, year=year, alttitle=alttitle)

    def _search_w_query(self, title: str, year: str, query: str = ''):
        title = sanitize_name(name=title)
        if len(title) < 2:
            title = f"{title} {year}"
        return self._get_results(query=f"{title} {query}".strip())

    def _get_results(self, query: Any = None) -> List[dict]:
        query, seed, resolution, exclude = self._parse_query(query)
        if exclude:
            exclude = query
            query = ''
        if self.cfg('include'):
            query += ' ' + self.cfg('include', default='')
        response = self._handler.get(
            endpoint="/api/v2.0/indexers/all/results",
            params={
                'Query': query,
                'Category[]': self._category,
            }
        )
        if not response.data or not isinstance(response.data, dict):
            return []
        results = []
        for item in sort_data(response.data.get('Results', []), param="Seeders", reverse=True):
            if media := self.map(item=item):
                results.append(media)
        if exclude:
            results = [r for r in results if all(e.lower() not in r['title'].lower() for e in exclude.split(' '))]
        if seed:
            results = [r for r in results if r['seeders'] >= seed]
        if resolution:
            results = [r for r in results if r['resolution'] == resolution]
        return self._remove_duplicates(results)

    def _parse_query(self, q: Any) -> tuple[str, int, str, bool]:
        if not q or q == '':
            return '', 0, None, False
        if isinstance(q, str):
            return q, 0, None, False
        if isinstance(q, dict):
            return q.get('include', ''), q.get('seeders', 0), q.get('resolution', 0),  q.get('exclude', False)
        log(f"Invalid query type: {type(q)}. Query must be a string or a dictionary. Skipp option!")
        return '', 0, None, False

    def _remove_duplicates(self, results: list):
        unique_titles = set()
        unique_results = []
        for result in results:
            if result['title'] not in unique_titles:
                unique_results.append(result)
                unique_titles.add(result['title'])
        return unique_results
