"""Jackett API consumer module."""

from typing import List, Any
from cineflow.core.logger import log
from cineflow.utils.misc import (
    sort_data, fix_imdbid, sanitize_name, media_resolution, search_preference_score,
    release_parsers,
)
from cineflow.core.bases.module import ConsumerBase
from cineflow.core.schema import (
    ModuleDefinition, Field, KIND, LIMIT, QUICK_MATCH, SEARCH_PREFERENCE, consumer_actions,
)


class Jackett(ConsumerBase):
    """
    Jackett API consumer module.

    Configuration:
        - url: Jackett base URL (e.g., http://localhost:9117/api/v2.0/indexers/all/results)
        - token: Jackett API key (required)
        - limit: Number of torrent results to return (default: 10)
        - kind: 'movie' (default) or 'tv'
        - season_pack_only: for 'tv', skip single-episode releases (default: true)

    Functions:
        - get: Collet most recent torrents
        - search: Search torrents for a given title.
    """

    CHECK_ENDPOINT = '/api/v2.0/indexers/all/results/torznab/api'
    CHECK_PARAMS = {'t': 'caps'}
    DEFINITION = ModuleDefinition(
        id='jackett', label='Jackett', category='indexer', connection_test=True,
        description="Torrent indexer proxy: recent releases and release search.",
        fields=(
            Field('url', 'url', 'URL', "Jackett base URL, e.g. http://jackett:9117.", required=True),
            Field('token', 'secret', 'API key', "Jackett API key.", required=True),
            KIND, LIMIT, QUICK_MATCH, SEARCH_PREFERENCE,
            Field('include', 'string', 'Required words', "Words added to every search.", step=True),
            Field('size_limit_gb', 'number', 'Size limit (GB)',
                  "Skip larger releases; 0 means no limit.", minimum=0, step=True),
            Field('season_pack_only', 'boolean', 'Season packs only',
                  "For TV, skip single-episode releases.", default=True, step=True),
        ),
        actions=consumer_actions('Jackett', query=(
            Field('include', 'string', 'Include words', "All words must be in the release name."),
            Field('exclude', 'string', 'Exclude words', "Release names with these words are dropped."),
            Field('seeders', 'integer', 'Minimum seeders', minimum=0),
            Field('resolution', 'select', 'Resolution',
                  options=('360p', '480p', '720p', '1080p', '1440p', '2160p', '4320p')),
            Field('size', 'number', 'Maximum size (GB)', minimum=0),
        )),
    )

    def __init__(self, config: dict = None) -> None:
        super().__init__(config=config, required=['url', 'token'])
        self.cache_time = 3600
        self._category = '2000' if self._kind == "movie" else '5000'
        release_mappings, release_transforms = release_parsers(kind=self._kind, source='Title')
        self._data_mappings = {
            **release_mappings,
            'link': ['Link', 'MagnetUri'],
            'size': ['Size'],
            'torrent': ['Title'],
            'seeders': ['Seeders'],
            'resolution': ['Title', 'CategoryDesc'],
            'imdbid': ['Imdb'],
        }
        self._data_transforms = {
            **release_transforms,
            'resolution': media_resolution,
            'imdbid': fix_imdbid,
            'size': lambda x: int(x) / (1024 * 1024 * 1024),
        }
        self.params = {
            'apikey': self.cfg('token'),
        }

    def get(self, query: Any = None) -> List[dict] | None:
        """Collect torrents from Jackett."""
        results = self._get_results(keywords='')
        if results is None:
            return None
        if query:
            results = self._apply_query(results=results, query=query)
        results = self._apply_search_pref(results)
        results = self._apply_size_limit(results=results)
        results = self._remove_duplicates(results)
        return results[:self._limit] if results else []

    def search(self, media: dict) -> dict:
        """Search torrents for the given title."""
        if not media.get('title') or (self._kind != 'tv' and not media.get('year')):
            log(f"Item missing required fields: {media}", level='DEBUG')
            return None
        if match := self._match_result(media=media):
            return match
        if media.get('alttitle') != media.get('title'):
            if match := self._match_result(media=media, titlekey='alttitle'):
                return match
        return None

    def _match_result(self, media: dict, titlekey: str = 'title'):
        results = self._search_w_title(media=media, titlekey=titlekey)
        if results is None:
            return None
        results = self._apply_search_pref(results)
        return self.match(results=results, media=media)

    def _search_w_title(self, media: dict, titlekey: str = 'title') -> List[dict] | None:
        title = sanitize_name(name=media.get(titlekey))
        if not title or len(title) < 2:
            return []
        if self._kind == 'tv':
            # series release names rarely carry the show year
            results = self._get_results(keywords=title)
            return None if results is None else self._apply_size_limit(results)
        results = self._get_results(keywords=f"{title} {media.get('year')}")
        if results is None:
            return None
        if results:
            return self._apply_size_limit(results)
        if len(title) < 3:
            title = f"{title} {media.get('year')}"
        results = self._get_results(keywords=title)
        if results is None:
            return None
        results = self._apply_size_limit(results)
        return results

    def _apply_search_pref(self, results: list) -> list:
        query_pref = list(self.cfg('search_preference', default=[]))
        return sorted(
            results,
            key=lambda result: search_preference_score(result.get('torrent'), query_pref),
            reverse=True,
        )

    def _apply_size_limit(self, results: list) -> list:
        limit = int(self.cfg('size_limit_gb', default=0))
        if not limit:
            return results
        # unknown size cannot be proven to fit the limit
        return [r for r in results if r.get('size') is not None and r['size'] <= limit]

    def _get_results(self, keywords: str = None) -> List[dict] | None:
        if self.cfg('include'):
            keywords += ' ' + self.cfg('include', default='')
        response = self._handler.get(
            endpoint="/api/v2.0/indexers/all/results",
            params={
                'Query': keywords,
                'Category[]': self._category,
            }
        )
        if not 200 <= response.status < 300:
            log(f"Jackett API error {response.status}.", level="ERROR")
            return None
        if (
            not isinstance(response.data, dict)
            or not isinstance(response.data.get('Results'), list)
        ):
            log("Invalid response from Jackett API.", level="ERROR")
            return None
        results = []
        sorted_items = sort_data(response.data.get('Results', []), param="Seeders", reverse=True)
        for item in sorted_items:
            if media := self.map(item=item):
                results.append(media)
        if self._kind == 'tv' and self.cfg('season_pack_only', default=True):
            results = [item for item in results if item.get('episode') is None]
        return results

    def _parse_query(self, q: Any) -> tuple[str, int, str, Any, int]:
        default = '', 0, None, False, 0
        if not q:
            return default
        if isinstance(q, str):
            return q, 0, None, False, 0
        if isinstance(q, dict):
            return (
                q.get('include', ''), q.get('seeders', 0), q.get('resolution', 0),
                q.get('exclude', False), int(q.get('size', 0) or 0),
            )
        log(f"Invalid query type: {type(q)}. Query must be a string or a dictionary. Skipp option!")
        return default

    @staticmethod
    def _query_words(value: Any) -> list[str]:
        """Return lower-case filter words from a string or a list."""
        if isinstance(value, (list, tuple)):
            return [str(word).lower() for word in value if str(word).strip()]
        return [word.lower() for word in str(value or '').split()]

    def _apply_query(self, results: list, query: dict) -> list:
        """Filter results by the query.

        ``include`` words must all be present. ``exclude: true`` inverts the
        ``include`` filter; a string or list ``exclude`` value names words that
        must not be present, while ``include`` still applies.
        """
        include, seed, resolution, exclude, size = self._parse_query(query)
        if seed:
            results = [r for r in results if (r.get('seeders') or 0) >= seed]
        if resolution:
            results = [r for r in results if r.get('resolution') == resolution]
        if size and size > 0:
            results = [r for r in results if r.get('size') is not None and r['size'] <= size]
        include_words = self._query_words(include)
        if exclude is True:
            exclude_words, include_words = include_words, []
        elif exclude:
            exclude_words = self._query_words(exclude)
        else:
            exclude_words = []
        if exclude_words:
            results = [
                r for r in results
                if all(word not in str(r.get('torrent', '')).lower() for word in exclude_words)
            ]
        if include_words:
            results = [
                r for r in results
                if all(word in str(r.get('torrent', '')).lower() for word in include_words)
            ]
        return results

    def _remove_duplicates(self, results: list) -> list:
        filtered = []
        seen_titles = set()
        for item in results:
            title_year = f"{item.get('title')} ({item.get('year')})"
            if self._kind == 'tv':
                title_year += f" S{item.get('season')}E{item.get('episode')}"
            if title_year not in seen_titles:
                filtered.append(item)
                seen_titles.add(title_year)
            else:
                log(f"Duplicate torrent found and removed: {item.get('torrent')}", level='DEBUG')
        return filtered
