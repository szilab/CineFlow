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
    if expression == 'exists' and left is not None:
        return True
    if expression == 'missing' and left is None:
        return True
    if expression == 'none' and right is None:
        return True
    if left and right and left.isdigit() and right.isdigit():
        left = int(left)
        right = int(right)
        if expression == 'eq':
            return left == right
        if expression == 'lt':
            return left < right
        if expression == 'gt':
            return left > right
    else:
        if not wcase:
            left = left.lower() if left else ''
            right = right.lower() if right else ''
        if expression == 'eq':
            return left == right
        if expression == 'ne':
            return left != right
        if expression == 'contains':
            return right in left
    return False


def load_module(name: str) -> object:
    """Load a module by its name."""
    directory = Path(__file__).resolve().parent.parent / 'modules'
    for file in directory.iterdir():
        if not str(file).endswith(".py") or str(file).startswith("__"):
            continue
        if name == str(file.name)[:-3]:
            module_obj = importlib.import_module(f"modules.{name}")
            class_name = f"{name[0].capitalize()}{name[1:]}"
            if hasattr(module_obj, class_name):
                return getattr(module_obj, class_name)
    return None
