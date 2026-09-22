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
