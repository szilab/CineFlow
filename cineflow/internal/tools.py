"""Emtpy module"""

import json
import os
from pathlib import Path
from typing import List, Dict
from cineflow.core.logger import log
from cineflow.core.schema import ModuleDefinition, ActionDefinition, Field, INPUT_DATA, INPUT_NONE

FILENAME = Field('filename', 'string', 'File name', "File in DEBUG_DIRECTORY.", default='exported_data.json')


class Tools():  # pylint: disable=too-few-public-methods
    """Tools module class"""

    DEFINITION = ModuleDefinition(
        id='tools', label='Tools', category='internal',
        description="Data helpers: de-duplication and debug export/import.",
        actions=(
            ActionDefinition('remove_duplicates', 'Remove duplicates',
                             "Drop items with an already seen IMDb ID, TMDb ID or title and year.",
                             input=INPUT_DATA),
            ActionDefinition('data_export', 'Export data', "Write the items to a JSON file.",
                             input=INPUT_DATA, output='none', arguments=(FILENAME,), side_effects=True),
            ActionDefinition('data_import', 'Import data', "Read items from a JSON file.",
                             input=INPUT_NONE, arguments=(FILENAME,)),
        ),
    )

    def __init__(self, config: dict = None) -> None:
        """Initialize the module."""
        self.name = self.__class__.__name__.lower()
        self._cfg = config or {}

    def data_export(self, data: List[Dict], filename: str = 'exported_data.json'):
        """Export data to a file"""
        full_path = Path(os.environ.get("DEBUG_DIRECTORY", "/tmp/cineflow"), filename)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        with full_path.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
        log(f"Data exported to '{full_path}'.")

    def data_import(self, filename: str = 'exported_data.json') -> List[Dict]:
        """Import data from a file"""
        path = Path(filename)
        if not path.is_absolute():
            path = Path(os.environ.get("DEBUG_DIRECTORY", "/tmp/cineflow"), path)
        if not path.exists():
            log(f"File '{path}' not found.", level='WARNING')
            return []
        with path.open('r', encoding='utf-8') as f:
            data = json.load(f)
        log(f"Data imported from '{path}'.")
        return data

    def remove_duplicates(self, data: List[Dict]):
        """Loop on data and filter out duplicates"""
        filtered = []
        imdbids = set()
        tmdbids = set()
        name_years = set()
        for item in data:
            imdbid = item.get('imdbid')
            if imdbid and imdbid in imdbids:
                log(f"Item '{item.get('title')}' ({item.get('year')}) [{item.get('imdbid')}] is a duplicate.")
                continue
            tmdbid = item.get('tmdbid')
            if tmdbid and tmdbid in tmdbids:
                log(f"Item '{item.get('title')}' ({item.get('year')}) [{item.get('tmdbid')}] is a duplicate.")
                continue
            title_year = (item.get('title'), item.get('year'))
            if all(title_year) and title_year in name_years:
                log(f"Item '{item.get('title')}' ({item.get('year')}) is a duplicate.")
                continue
            filtered.append(item)
            if imdbid:
                imdbids.add(imdbid)
            if tmdbid:
                tmdbids.add(tmdbid)
            if all(title_year):
                name_years.add(title_year)
        return filtered
