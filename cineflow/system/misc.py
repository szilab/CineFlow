"""Miscellaneous functions for the system library."""
import importlib
import re
from pathlib import Path


def sanitize_name(name: str, replace_with: str = "") -> str:
    """Sanitize a directory or file name by removing invalid characters."""
    return re.sub(r'[\\\/:\*\?"<>\|]', replace_with, name)


def sort_data(data: list, param: str, reverse: bool = False) -> list:
    """Sort data based on a parameter."""
    return sorted(data, key=lambda x: x.get(param), reverse=reverse)


def __title_groups(title: str) -> None:
    result = re.search(r'(.+)\.([12]\d\d\d)\.', title)
    if not result or len(groups := result.groups()) < 2:
        return None
    return groups


def media_title(title: str) -> None:
    if group := __title_groups(title):
        return group[0].replace('.', ' ').strip()
    return None


def media_year(title: str) -> None:
    if group := __title_groups(title):
        return group[1]
    return None


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
