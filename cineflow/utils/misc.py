"""Miscellaneous functions for the system library."""
import re


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
    """Return the configured preference score for a torrent release name."""
    if not torrent:
        return 0
    preferences = list(preferences or [])
    preferences.append('')
    return sum(
        len(preferences) - index
        for index, preference in enumerate(preferences)
        if str(preference).lower() in str(torrent).lower()
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

# "S01", "S01E02", "S01.E02", "S1E2" or "Season 1" after the show title
_SERIES_MARKER = re.compile(
    r'(?:^|\.)(?:S(\d{1,2})(?:\.?E(\d{1,3}))?|Season\.?(\d{1,2}))(?=[.\-_\[]|$)',
    flags=re.IGNORECASE,
)
_TRAILING_YEAR = re.compile(r'^(.*?)[.(\[]*([12]\d{3})[)\]]*$')


def series_info(name: str) -> dict | None:
    """Parse a TV release name into title, optional year, season and episode.

    Returns None when the name has no season marker. ``episode`` is None for
    season packs such as ``Show.S02.1080p`` or ``Show Season 2``.
    """
    if not name:
        return None
    text = re.sub(r'\s+', '.', str(name).strip())
    marker = _SERIES_MARKER.search(text)
    if not marker or marker.start() == 0:
        return None
    title = text[:marker.start()].strip('.-_ ')
    year = None
    if match := _TRAILING_YEAR.match(title):
        if match.group(1).strip('.-_ ('):
            title, year = match.group(1), match.group(2)
    title = title.replace('.', ' ').replace('_', ' ').strip(' -([')
    if not title:
        return None
    season = marker.group(1) or marker.group(3)
    episode = marker.group(2)
    return {
        'title': title,
        'year': year,
        'season': int(season),
        'episode': int(episode) if episode else None,
    }


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


def release_parsers(kind: str, source: str) -> tuple[dict, dict]:
    """Return the mappings and transforms that parse a release name field.

    ``source`` is the name of the raw field holding the release name.
    """
    if kind == 'tv':
        mappings = {
            'title': [source], 'year': [source], 'season': [source], 'episode': [source],
        }
        transforms = {
            'title': series_title, 'year': series_year,
            'season': series_season, 'episode': series_episode,
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
    elif left and right and left.isdigit() and right.isdigit():
        left = int(left)
        right = int(right)
        if expression == 'eq':
            outcome = left == right
        elif expression == 'lt':
            outcome = left < right
        elif expression == 'gt':
            outcome = left > right
    else:
        outcome = _evaluate_text(left=left, right=right, expression=expression, wcase=wcase)
    return outcome


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
        return bool(re.search(
            rf'(?<![A-Za-z0-9]){re.escape(str(right))}(?![A-Za-z0-9])',
            str(left),
            flags=0 if wcase else re.IGNORECASE,
        ))
    return False


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
