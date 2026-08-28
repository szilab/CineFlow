"""Emtpy module"""

import os
import json
from typing import List, Dict
from cineflow.core.logger import log


class Tools():  # pylint: disable=too-few-public-methods
    """Tools module class"""

    def __init__(self, config: dict = None) -> None:
        """Initialize the module."""
        self.name = self.__class__.__name__.lower()
        self._cfg = config or {}

    def data_export(self, data: List[Dict], filename: str = 'exported_data.json'):
        """Export data to a file"""
        full_path = os.path.join(os.environ.get("DEBUG_DIRECTORY", "/tmp/cineflow"), filename)
        if not os.path.exists(os.path.basename(full_path)):
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        log(f"Data exported to '{full_path}'.")

    def data_import(self, filename: str = 'exported_data.json') -> List[Dict]:
        """Import data from a file"""
        if not os.path.isabs(filename):
            filename = os.path.join(os.environ.get("DEBUG_DIRECTORY", "/tmp/cineflow"), filename)
        if not os.path.exists(filename):
            log(f"File '{filename}' not found.", level='WARNING')
            return []
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
        log(f"Data imported from '{filename}'.")
        return data

    def remove_duplicates(self, data: List[Dict]):
        """Loop on data and filter out duplicates"""
        filtered = data.copy()
        imdbids = []
        for item in filtered:
            if item.get('imdbid') and item['imdbid'] in imdbids:
                log(f"Item '{item.get('title')}' ({item.get('year')}) [{item.get('imdbid')}] is a duplicate.")
                filtered.remove(item)
            else:
                imdbids.append(item.get('imdbid'))

        tmdbids = []
        for item in filtered:
            if item.get('tmdbid') and item['tmdbid'] in tmdbids:
                log(f"Item '{item.get('title')}' ({item.get('year')}) [{item.get('tmdbid')}] is a duplicate.")
                filtered.remove(item)
            else:
                tmdbids.append(item.get('tmdbid'))

        name_years = []
        for item in filtered:
            if (
                item.get('title') and
                item.get('year') and
                f"{item['title']} ({item['year']})" in name_years
            ):
                log(f"Item '{item.get('title')}' ({item.get('year')}) is a duplicate.")
                filtered.remove(item)
            else:
                name_years.append(f"{item['title']} ({item['year']})")
        return filtered
