"""This module contains tility functions"""

import re
import os
import importlib
import sys
from urllib import request, error
import requests
from bases.abs import ModuleBase
from system.logger import log


def list_modules() -> list:
    """List all modules in the modules directory."""
    directory = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'modules'
    )
    modules = []
    for file in os.listdir(directory):
        if not file.endswith(".py") or file.startswith("__"):
            continue
        name = file[:-3]
        module = importlib.import_module(f"{os.path.basename(directory)}.{name}")
        class_name = f"{name[0].capitalize()}{name[1:]}Module"
        if hasattr(module, class_name) and issubclass(getattr(module, class_name), ModuleBase):
            modules.append({'name': name, 'class': getattr(module, class_name)})
        else:
            log(f"Module '{name}' is not valid", level="ERROR")
            sys.exit(1)
    return modules


def download_file(url, path: str) -> None:
    """Download a file from a URL and save it to a local path."""
    try:
        response = requests.get(url, stream=True, timeout=10)
        response.raise_for_status()
        with open(path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
        log(f"File downloaded successfully from {url} to {path}.", level='DEBUG')
    except requests.RequestException as e:
        log(f"Failed to download file from {url}: {e}", level='ERROR')


def get_file(url: str) -> bytes:
    """Retrieve file data from a URL."""
    try:
        with request.urlopen(url) as response:
            return response.read()
    except error.HTTPError as e:
        log(f"Failed to retrieve file from {url}: {e}", level='ERROR')
        return None


def filter_data(
        filters: str,
        data: list,
        param: str,
        negative: bool = False,
        integer: bool = False
    ) -> list:
    """Filter data based on a list of filters."""
    for f in filters.split(","):
        for item in data or []:
            if not integer:
                if negative and f.lower() not in item.get(param, "").lower():
                    data.remove(item)
                elif not negative and f.lower() in item.get(param, "").lower():
                    data.remove(item)
            else:
                if negative and int(f) >= item.get(param, 0):
                    data.remove(item)
                elif not negative and int(f) <= item.get(param, 0):
                    data.remove(item)
    return data


def sort_data(data: list, param: str, reverse: bool = False) -> list:
    """Sort data based on a parameter."""
    return sorted(data, key=lambda x: x.get(param), reverse=reverse)


def st(title: str) -> str:
    """Sanitize title."""
    if not title:
        return ""
    sanitized = re.sub(r'[\\/\*\?\!:"<>\|#\'\"]', "", title).lower()
    sanitized = sanitized.replace('.', ' ')
    sanitized = sanitized.replace('&', 'and')
    sanitized = sanitized.replace('@', 'and')
    return sanitized.strip()
