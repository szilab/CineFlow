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
            'size': lambda x: int(x) / (1024 * 1024 * 1024),
        }
        self.params = {
            'apikey': self.cfg('token'),
        }

    def get(self, query: Any = None):
        """Collect torrents from Jackett."""
        results = self._get_results(keywords='')
        if query:
            results = self._apply_query(results=results, query=query)
        results = self._apply_search_pref(results)
        results = self._apply_size_limit(results=results)
        results = self._remove_duplicates(results)
        return results[:self._limit] if results else []

    def search(self, media: dict) -> dict:
        """Search torrents for the given title."""
        if not media.get('title') or not media.get('year'):
            log(f"Item missing required fields: {media}", level='DEBUG')
            return None
        if match := self._match_result(media=media):
            return match
        if media.get('alttitle') != media.get('title'):
            if match := self._match_result(media=media, titlekey='alttitle'):
                return match
        return None

    def _match_result(self, media: dict, titlekey: dict = 'title'):
        results = self._search_w_title(media=media, titlekey=titlekey)
        results = self._apply_search_pref(results)
        return self.match(results=results, media=media)

    def _search_w_title(self, media: dict, titlekey: str = 'title'):
        title = sanitize_name(name=media.get(titlekey))
        if not title or len(title) < 2:
            return None
        if len(title) < 3:
            title = f"{title} {media.get('year')}"
        results = self._get_results(keywords=title)
        results = self._apply_size_limit(results)
        return results

    def _apply_search_pref(self, results: list):
        query_pref = list(self.cfg('search_preference', default=[]))
        query_pref.append('')
        scored_res = [{'s': None, 'r': r} for r in results]
        for item in scored_res:
            score = 0
            for q in query_pref:
                if str(q).lower() in str(item['r'].get('torrent', '')).lower():
                    score += (len(query_pref) - query_pref.index(q))
            item['s'] = score
        scored_res = sorted(scored_res, key=lambda x: x['s'], reverse=True)
        filtered = [r['r'] for r in scored_res]
        return filtered

    def _apply_size_limit(self, results: list):
        limit = int(self.cfg('size_limit_gb', default=0))
        if not limit:
            return results
        return [r for r in results if r['size'] <= limit]

    def _get_results(self, keywords: str = None) -> List[dict]:
        if self.cfg('include'):
            keywords += ' ' + self.cfg('include', default='')
        response = self._handler.get(
            endpoint="/api/v2.0/indexers/all/results",
            params={
                'Query': keywords,
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

    def _parse_query(self, q: Any) -> tuple[str, int, str, bool]:
        default = '', 0, None, False, 0
        if not q or q == '':
            return default
        if isinstance(q, str):
            return q, 0, None, False, 0
        if isinstance(q, dict):
            return \
                q.get('include', ''), q.get('seeders', 0), \
                q.get('resolution', 0),  q.get('exclude', False), \
                (int(q.get('size', 0)) or 0)
        log(f"Invalid query type: {type(q)}. Query must be a string or a dictionary. Skipp option!")
        return default

    def _apply_query(self, results: list, query: dict) -> list:
        query, seed, resolution, exclude, size = self._parse_query(query)
        if seed:
            results = [r for r in results if r['seeders'] >= seed]
        if resolution:
            results = [r for r in results if r['resolution'] == resolution]
        if size and size > 0:
            results = [r for r in results if r['size'] <= size]
        if exclude:
            results = [r for r in results if all(e.lower() not in r['torrent'].lower() for e in query.split(' '))]
        if query:
            results = [r for r in results if all(q.lower() in r['torrent'].lower() for q in query.split(' '))]
        return results

    def _remove_duplicates(self, results: list):
        filtered = []
        seen_titles = set()
        for item in results:
            title_year = f"{item.get('title')} ({item.get('year')})"
            if title_year not in seen_titles:
                filtered.append(item)
                seen_titles.add(title_year)
            else:
                log(f"Duplicate torrent found and removed: {item.get('torrent')}", level='DEBUG')
        return filtered
