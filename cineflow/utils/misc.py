"""Miscellaneous functions for the system library."""
import re
from typing import Any


def sanitize_name(name: str, replace_with: str = "") -> str:
    """Sanitize a name by removing invalid characters."""
    if not name:
        return ''
    name = re.sub(r'[\-]', ' ', str(name))
    return re.sub(r'[\.\\\/:\*\?\!"<>\|\'\&]', replace_with, str(name))


def sanitize_path(name: str, replace_with: str = "") -> str:
    """Sanitize a directory or file by removing invalid characters."""
    return re.sub(r'[\\\/:\*\?"<>\|\']', replace_with, str(name))


def sort_data(data: list, param: str, reverse: bool = False) -> list:
    """Sort data based on a parameter."""
    return sorted(data, key=lambda x: x.get(param), reverse=reverse)


def search_preference_score(torrent: str, preferences: list | None = None) -> int:
    """Return the preference score of a torrent release name; a higher score is a better release.

    The words are a strict priority: a release with the first word beats every
    release without it, whatever else they contain; the second word only
    decides between releases equal on the first, and so on. Every named
    release scores at least 1.
    """
    if not torrent:
        return 0
    name = str(torrent).lower()
    words = list(preferences or [])
    return 1 + sum(
        2 ** (len(words) - index)
        for index, word in enumerate(words)
        if str(word).lower() and str(word).lower() in name
    )


def __title_groups(title: str) -> None:
    title = title.replace(' ', '.')
    result = re.search(r'(.+)\.([12]\d\d\d)\.', title)
    if not result or len(groups := result.groups()) < 2:
        return None
    return groups


def media_title(title: str):
    """Extract media title from a given string."""
    if group := __title_groups(title):
        return group[0].replace('.', ' ').strip()
    return None


def media_year(title: str):
    """Extract media year from a given string."""
    if group := __title_groups(title):
        return group[1]
    return None


MEDIA_KINDS = ('movie', 'tv')

# "S01", "S01E02", "S01.E02", "S1E2", "Season 1" or "Seasons 1" after the show title
_SERIES_MARKER = re.compile(
    r'(?:^|\.)(?:S(\d{1,2})(?:\.?E(\d{1,3}))?|Seasons?\.?(\d{1,2}))(?=[.\-_\[]|E\d|$)',
    flags=re.IGNORECASE,
)
# what may follow a season marker: a range "-S03", "-03", "-3" or more seasons ".S02"
_SEASON_RANGE = re.compile(r'^-S?(\d{1,2})(?![\dE])', flags=re.IGNORECASE)
_SEASON_NEXT = re.compile(r'^\.S(\d{1,2})(?=[.\-_\[]|$)', flags=re.IGNORECASE)
# what may follow an episode marker: "-E03", "-03" or "E02" (several episodes)
_EPISODE_RANGE = re.compile(r'^(?:-E?|E)(\d{1,3})(?!\d)', flags=re.IGNORECASE)
# a whole series without season numbers, e.g. "Show.Complete.Series.1080p"
_COMPLETE_MARKER = re.compile(r'(?:^|\.)Complete(?=[.\-_\[]|$)', flags=re.IGNORECASE)
_TRAILING_YEAR = re.compile(r'^(.*?)[.(\[]*([12]\d{3})[)\]]*$')


def _series_title(text: str) -> tuple[str, str | None]:
    """Return the show title and optional year from the release name part before the marker."""
    title = text.strip('.-_ ')
    year = None
    if match := _TRAILING_YEAR.match(title):
        if match.group(1).strip('.-_ ('):
            title, year = match.group(1), match.group(2)
    return title.replace('.', ' ').replace('_', ' ').strip(' -(['), year


def series_info(name: str) -> dict | None:
    """Parse a TV release name into title, optional year, season and episode.

    Returns None when the name has no season marker. ``episode`` is None for
    season packs such as ``Show.S02.1080p`` or ``Show Season 2``. A pack of
    several seasons (``S01-S03``, ``Season 1-3``, ``S01.S02``) lists them in
    ``seasons``; several episodes (``S02E01-E03``, ``S02E01E02``) are listed in
    ``episodes``; a whole series without season numbers (``Show.Complete``) has
    ``complete: True`` and no season.
    """
    if not name:
        return None
    text = re.sub(r'\s+', '.', str(name).strip())
    marker = _SERIES_MARKER.search(text)
    if not marker or marker.start() == 0:
        complete = _COMPLETE_MARKER.search(text)
        if not complete or complete.start() == 0:
            return None
        title, year = _series_title(text[:complete.start()])
        if not title:
            return None
        return {'title': title, 'year': year, 'season': None, 'episode': None, 'seasons': None,
                'episodes': None, 'complete': True}
    title, year = _series_title(text[:marker.start()])
    if not title:
        return None
    season = int(marker.group(1) or marker.group(3))
    episode = int(marker.group(2)) if marker.group(2) else None
    seasons = [season]
    episodes = None
    if episode is not None:
        if (span := _EPISODE_RANGE.match(text[marker.end():])) and int(span.group(1)) > episode:
            episodes = list(range(episode, int(span.group(1)) + 1))
    else:
        rest = text[marker.end():]
        if (span := _SEASON_RANGE.match(rest)) and int(span.group(1)) > season:
            seasons = list(range(season, int(span.group(1)) + 1))
        else:
            while more := _SEASON_NEXT.match(rest):
                seasons.append(int(more.group(1)))
                rest = rest[more.end():]
    return {
        'title': title,
        'year': year,
        'season': season,
        'episode': episode,
        'seasons': sorted(set(seasons)) if len(seasons) > 1 else None,
        'episodes': episodes,
        'complete': False,
    }


def plan_season(have: set, watched: set, aired: dict | None,
                watched_percent: float) -> tuple[int, list[int] | None] | None:
    """Return the season of a series to download next and its missing episodes, or None.

    ``have`` and ``watched`` are (season, episode) pairs in the libraries and
    watched by anyone; ``aired`` maps season numbers to their aired episode
    counts (empty or None when unknown, then a season is assumed to exist).

    - A series without episodes gets season 1 (the whole season: no episode list).
    - Aired episodes missing from the latest season in the libraries come first
      (an airing season): that season with the list of those episodes.
    - Otherwise the whole next season follows once ``watched_percent`` of the
      latest season's episodes in the libraries are watched.
    """
    aired = {int(key): value for key, value in (aired or {}).items()}

    def exists(season: int) -> bool:
        return not aired or bool(aired.get(season))

    if not have:
        return (1, None) if exists(1) else None
    latest = max(season for season, _ in have)
    episodes = {pair for pair in have if pair[0] == latest}
    if missing := [number for number in range(1, (aired.get(latest) or 0) + 1) if (latest, number) not in episodes]:
        return latest, missing
    if len(episodes & watched) * 100 < watched_percent * len(episodes):
        return None
    return (latest + 1, None) if exists(latest + 1) else None


def release_episodes(item: dict) -> list[int]:
    """Return the episodes a TV release covers; [] for a season or series pack."""
    if item.get('episode') is None:
        return []
    return list(item.get('episodes') or [item['episode']])


def release_seasons(item: dict) -> list[int] | None:
    """Return the seasons a TV release covers: [] for a single episode, None for a whole series."""
    if item.get('complete'):
        return None
    if item.get('episode') is not None or item.get('season') is None:
        return []
    return list(item.get('seasons') or [item['season']])


def series_title(name: str):
    """Extract the show title from a TV release name."""
    return (series_info(name) or {}).get('title')


def series_year(name: str):
    """Extract the optional show year from a TV release name."""
    return (series_info(name) or {}).get('year')


def series_season(name: str):
    """Extract the season number from a TV release name."""
    return (series_info(name) or {}).get('season')


def series_episode(name: str):
    """Extract the episode number from a TV release name, None for season packs."""
    return (series_info(name) or {}).get('episode')


# a Jellyfin folder name: "Title (year) [tmdbid-N]" with any text after it;
# the year or the TMDb ID may be missing
_JELLYFIN_NAMES = (
    re.compile(r'^(?P<title>.+?) \((?P<year>[12]\d{3})\)(?: \[tmdbid-(?P<tmdbid>\d+)\])?'),
    re.compile(r'^(?P<title>.+?) \[tmdbid-(?P<tmdbid>\d+)\]'),
)


def jellyfin_name(name: str) -> dict | None:
    """Parse a Jellyfin folder name into title, year and tmdbid; None for other names."""
    text = str(name or '').strip()
    for pattern in _JELLYFIN_NAMES:
        if match := pattern.match(text):
            found = match.groupdict()
            return {
                'title': found['title'].strip(),
                'year': found.get('year'),
                'tmdbid': int(found['tmdbid']) if found.get('tmdbid') else None,
            }
    return None


def release_parsers(kind: str, source: str, folder_names: bool = False) -> tuple[dict, dict]:
    """Return the mappings and transforms that parse a release name field.

    ``source`` is the name of the raw field holding the release name. With
    ``folder_names`` a Jellyfin folder name (a torrent the ``rename`` action
    renamed, with any suffix) gives the title, year and tmdbid when the release
    name parser finds no title; its season is unknown.
    """
    mappings, transforms = _release_parsers(kind=kind, source=source)
    if not folder_names:
        return mappings, transforms

    title = transforms['title']

    def parse(key: str, parser):
        def transform(name):
            # a release name keeps its parser; a folder name is read when it gives no title
            folder = jellyfin_name(name) if key == 'tmdbid' or not title(name) else None
            if folder is not None:
                return folder.get(key)
            return parser(name) if parser else None
        return transform

    mappings['tmdbid'] = [source]
    transforms = {key: parse(key, parser) for key, parser in transforms.items()}
    transforms['tmdbid'] = parse('tmdbid', None)
    return mappings, transforms


def _release_parsers(kind: str, source: str) -> tuple[dict, dict]:
    """Return the mappings and transforms that parse a release name."""
    if kind == 'tv':
        mappings = {
            'title': [source], 'year': [source], 'season': [source], 'episode': [source],
            'seasons': [source], 'episodes': [source], 'complete': [source],
        }
        transforms = {
            'title': series_title, 'year': series_year,
            'season': series_season, 'episode': series_episode,
            'seasons': lambda name: (series_info(name) or {}).get('seasons'),
            'episodes': lambda name: (series_info(name) or {}).get('episodes'),
            'complete': lambda name: (series_info(name) or {}).get('complete') or None,
        }
        return mappings, transforms
    return {'title': [source], 'year': [source]}, {'title': media_title, 'year': media_year}


def media_resolution(title: str):
    """Extract media resolution from a given string."""
    ret = 'N/A'
    if '360p' in title.lower():
        ret = '360p'
    if '480p' in title.lower():
        ret = '480p'
    if '720p' in title.lower():
        ret = '720p'
    if '1080p' in title.lower():
        ret = '1080p'
    if '1440p' in title.lower():
        ret = '1440p'
    if '2160p' in title.lower():
        ret = '2160p'
    if '4320p' in title.lower():
        ret = '4320p'
    return ret


def fix_imdbid(id_str: str):
    """Fix the IMDB ID."""
    if isinstance(id_str, dict) and id_str.get('Imdb'):
        id_str = id_str.get('Imdb')
    id_str = str(id_str).lower().strip()
    if id_str.startswith('tt'):
        id_str = id_str.replace('tt', '')
    if not id_str:
        return None
    try:
        id_num = int(id_str)
    except ValueError:
        return None
    return id_num


def evaluate(left: str, right: str, expression: str, wcase: bool = True) -> bool:
    """Evaluate the expression."""
    outcome = False
    if expression in ('exists', 'missing', 'none'):
        outcome = _evaluate_null_logic(left=left, right=right, expression=expression)
    elif _number(left) is not None and _number(right) is not None:
        left = _number(left)
        right = _number(right)
        if expression == 'eq':
            outcome = left == right
        elif expression == 'ne':
            outcome = left != right
        elif expression == 'lt':
            outcome = left < right
        elif expression == 'gt':
            outcome = left > right
    else:
        outcome = _evaluate_text(left=left, right=right, expression=expression, wcase=wcase)
    return outcome


def _number(value) -> float | None:
    """Return a numeric text as a number, else None."""
    try:
        return float(str(value).strip()) if value not in (None, '') else None
    except ValueError:
        return None


def _evaluate_text(left: str, right: str, expression: str, wcase: bool) -> bool:
    """Evaluate textual rule expressions."""
    if not wcase:
        left = left.lower() if left else ''
        right = right.lower() if right else ''
    if expression == 'eq':
        return left == right
    if expression == 'ne':
        return left != right
    if expression == 'contains':
        return right in left
    if expression == 'token':
        return has_word(left, right, case_sensitive=wcase)
    return False


def has_word(text: Any, word: Any, case_sensitive: bool = True) -> bool:
    """Return whether the text has the word as a whole token.

    Any character other than a letter A-Z or a digit separates words, so
    ``HUN`` is a word of ``Movie.2005-HUN_DVDRip`` but not of ``Hungry``.
    """
    if text is None or word is None or str(word) == '':
        return False
    return bool(re.search(
        rf'(?<![A-Za-z0-9]){re.escape(str(word))}(?![A-Za-z0-9])',
        str(text),
        flags=0 if case_sensitive else re.IGNORECASE,
    ))


def load_module(name: str) -> object:
    """Load a workflow module through the canonical package registries."""
    from cineflow import integrations, internal

    for registry in (integrations, internal):
        if module := registry.load_module(name):
            return module
    return None


def _evaluate_null_logic(left: str, right: str, expression: str) -> bool:
    if expression == 'exists':
        return left is not None
    if expression == 'missing':
        return left is None
    if expression == 'none':
        return right is None
    return False
