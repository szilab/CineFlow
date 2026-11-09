"""Jackett API consumer module."""

from dataclasses import replace
from datetime import date
from typing import List, Any
from cineflow.core.logger import log
from cineflow.utils.misc import (
    sort_data, fix_imdbid, sanitize_name, media_resolution, search_preference_score,
    release_parsers, release_seasons, release_episodes,
)
from cineflow.core.bases.module import ConsumerBase
from cineflow.core.schema import (
    ModuleDefinition, Field, LIMIT, consumer_actions,
)

RESOLUTIONS = ('360p', '480p', '720p', '1080p', '1440p', '2160p', '4320p')
# release filters of the module, shown and overridable on every 'get' step
RELEASE_FILTERS = ('min_seeders', 'resolution', 'size_limit_gb')


class Jackett(ConsumerBase):
    """
    Jackett API consumer module.

    Configuration:
        - url: Jackett base URL (e.g., http://localhost:9117/api/v2.0/indexers/all/results)
        - token: Jackett API key (required)
        - limit: safety cap of collected torrent results (default: 200)
        - kind: 'movie' (default) or 'tv', given by the flow
        - search_preference: release name preferences, given by the flow
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
            LIMIT,
            Field('min_seeders', 'integer', 'Minimum seeders',
                  "Skip releases with fewer seeders; 0 means no limit.", minimum=0, step=True),
            Field('resolution', 'select', 'Resolution', "Keep only releases of this resolution.",
                  options=RESOLUTIONS, step=True),
            Field('size_limit_gb', 'number', 'Maximum size (GB)',
                  "Skip larger releases; 0 means no limit.", minimum=0, step=True),
            Field('season_pack_only', 'boolean', 'Season packs only',
                  "For TV, skip single-episode releases when collecting releases or matching a series "
                  "without a chosen season. A chosen season still uses episodes when it has no pack.",
                  default=True, step=True),
        ),
        actions=tuple(replace(action, overrides=RELEASE_FILTERS) if action.id == 'get' else action
                      for action in consumer_actions('Jackett', query=(
                          Field('include', 'string', 'Include words', "All words must be in the release name.",
                                advanced=True),
                          Field('exclude', 'string', 'Exclude words',
                                "Release names with these words are dropped.", advanced=True),
                      ))),
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
        """Collect recent torrents from Jackett, at most ``limit``.

        Indexers answer one page per search (about 50-100 releases) and do not
        page further, so a search is joined by one with the current year added,
        which mostly returns other releases. The search is blank, or the
        ``include`` words of the query: a blank search only reaches the
        releases of the last day or two.
        """
        words, year = self._search_words(query), str(date.today().year)
        searches = [' '.join(words)] + ([] if year in words else [' '.join([*words, year])])
        results, seen = [], set()
        for keywords in searches:
            found = self._get_results(keywords=keywords)
            if found is None:
                return None
            for item in found:
                if (key := item.get('link') or item.get('torrent')) not in seen:
                    seen.add(key)
                    results.append(item)
        results.sort(key=lambda item: item.get('seeders') or 0, reverse=True)
        if query:
            results = self._apply_query(results=results, query=query)
        results = self._apply_search_pref(results)
        results = self._apply_size_limit(results=results)
        results = self._remove_duplicates(results)
        return results[:self._limit] if results else []

    def search(self, media: dict) -> dict:
        """Search torrents for the given title; a series with a ``season`` gets that season."""
        if not media.get('title') or (self._kind != 'tv' and not media.get('year')):
            log(f"Item missing required fields: {media}", level='DEBUG')
            return None
        if self._kind == 'tv' and isinstance(media.get('season'), int):
            return self._season_release(media)
        if match := self._match_result(media=media):
            return match
        if media.get('alttitle') != media.get('title'):
            if match := self._match_result(media=media, titlekey='alttitle'):
                return match
        return None

    def _season_release(self, media: dict) -> dict | list[dict] | None:
        """Return the release(s) of one season of a series.

        Missing episodes of a season (``wanted_episodes``) get episode releases
        only. A whole season gets a single-season pack, else releases of its
        aired episodes, else the multi-season pack with the fewest extra seasons.
        """
        season, wanted = media['season'], media.get('wanted_episodes')
        for titlekey in ('title', 'alttitle'):
            if titlekey == 'alttitle' and media.get('alttitle') in (None, media.get('title')):
                break
            title = sanitize_name(name=media.get(titlekey))
            if not title or len(title) < 2:
                continue
            results = self._season_results(title, season)
            if results is None:
                return None
            if not wanted:
                single = [item for item in results if release_seasons(item) == [season]]
                if match := self.match(results=single, media=media):
                    return match
            aired = (media.get('seasons_aired') or {})
            count = aired.get(season) or aired.get(str(season))
            episodes = wanted or (list(range(1, count + 1)) if count else None)
            if picks := self._episode_releases(results, media, season, episodes):
                return picks
            if wanted:
                continue
            # only when no single season and no episode exists: the pack with the fewest extra seasons
            several = [item for item in results
                       if (covered := release_seasons(item)) is None or (len(covered) > 1 and season in covered)]
            several.sort(key=lambda item: len(release_seasons(item) or range(1000)))
            if match := self.match(results=several, media=media):
                log(f"No single-season release of '{media.get('title')}' season {season}, "
                    f"using '{match.get('torrent')}'.")
                return match
        return None

    def _season_results(self, title: str, season: int) -> list[dict] | None:
        """Return the releases of a series title, with a second search for the season's episodes."""
        releases = []
        seen = set()
        for keywords in (title, f"{title} S{season:02d}"):
            results = self._get_results(keywords=keywords, packs_only=False)
            if results is None:
                return None
            for item in self._apply_size_limit(results):
                if (key := item.get('link') or item.get('torrent')) not in seen:
                    seen.add(key)
                    releases.append(item)
        return self._apply_search_pref(releases)

    def _episode_releases(self, results: list, media: dict, season: int, episodes: list | None) -> list[dict]:
        """Return releases covering the episodes of a season, one release per episode (or episode range).

        Without a known episode list every episode found is taken. A release of
        one episode is preferred to one of several; then the search preference.
        """
        candidates = [item for item in results if item.get('season') == season and release_episodes(item)]
        if episodes is None:
            episodes = sorted({number for item in candidates for number in release_episodes(item)})
        picks, covered = [], set()
        for number in episodes:
            if number in covered:
                continue
            options = sorted((item for item in candidates if number in release_episodes(item)),
                             key=lambda item: len(release_episodes(item)))
            if match := self.match(results=options, media=media):
                picks.append(match)
                covered.update(release_episodes(match))
        if picks:
            log(f"Season {season} of '{media.get('title')}': {len(picks)} episode release(s).")
        return picks

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
        """Apply the release filters of the module: size limit, minimum seeders, resolution."""
        limit = float(self.cfg('size_limit_gb', default=0) or 0)
        if limit:
            # unknown size cannot be proven to fit the limit
            results = [r for r in results if r.get('size') is not None and r['size'] <= limit]
        if seeders := int(self.cfg('min_seeders', default=0) or 0):
            results = [r for r in results if (r.get('seeders') or 0) >= seeders]
        if resolution := self.cfg('resolution'):
            results = [r for r in results if r.get('resolution') == resolution]
        return results

    def _get_results(self, keywords: str = None, packs_only: bool = True) -> List[dict] | None:
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
        if packs_only and self._kind == 'tv' and self.cfg('season_pack_only', default=True):
            results = [item for item in results if item.get('episode') is None]
        return results

    def _parse_query(self, q: Any) -> tuple[str, Any]:
        """Return the ``include`` and ``exclude`` words of a query."""
        if not q:
            return '', False
        if isinstance(q, str):
            return q, False
        if isinstance(q, dict):
            return q.get('include', ''), q.get('exclude', False)
        log(f"Invalid query type: {type(q)}. Query must be a string or a dictionary. Skipp option!")
        return '', False

    def _search_words(self, query: Any) -> list[str]:
        """Return the words every collected release must contain, sent to the indexers."""
        include, exclude = self._parse_query(query)
        return [] if exclude is True else self._query_words(include)

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
        include, exclude = self._parse_query(query)
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
