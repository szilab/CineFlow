"""Miscellaneous functions for the system library."""
import importlib
import re
from pathlib import Path


def sanitize_name(name: str, replace_with: str = "") -> str:
    """Sanitize a name by removing invalid characters."""
    return re.sub(r'[\.\\\/:\*\?\!"<>\|\'\-]', replace_with, str(name))


def sanitize_path(name: str, replace_with: str = "") -> str:
    """Sanitize a directory or file by removing invalid characters."""
    return re.sub(r'[\\\/:\*\?"<>\|\']', replace_with, str(name))


def sort_data(data: list, param: str, reverse: bool = False) -> list:
    """Sort data based on a parameter."""
    return sorted(data, key=lambda x: x.get(param), reverse=reverse)


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
    ret = None
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
    id_str = str(id_str).strip()
    if not id_str or len(id_str) < 3:
        return None
    if id_str.startswith('tt'):
        return id_str.lower()
    return f"tt{str(id_str)}"


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
        if not wcase:
            left = left.lower() if left else ''
            right = right.lower() if right else ''
        if expression == 'eq':
            outcome = left == right
        elif expression == 'ne':
            outcome = left != right
        elif expression == 'contains':
            outcome = right in left
    return outcome


def load_module(name: str) -> object:
    """Load a module by its name."""
    directory = Path(__file__).resolve().parent.parent / 'modules'
    for file in directory.iterdir():
        if not str(file).endswith(".py") or str(file).startswith("__"):
            continue
        if name == str(file.name)[:-3]:
            module_obj = importlib.import_module(f"cineflow.modules.{name}")
            class_name = f"{name[0].capitalize()}{name[1:]}"
            if hasattr(module_obj, class_name):
                return getattr(module_obj, class_name)
    return None


def _evaluate_null_logic(left: str, right: str, expression: str) -> bool:
    if expression == 'exists':
        return left is not None
    if expression == 'missing':
        return left is None
    if expression == 'none':
        return right is None
    return False
