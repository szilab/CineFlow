"""Emtpy module"""

from typing import List, Dict
from cineflow.system.logger import log


class Tools():
    """Tools module class"""

    def __init__(self, config: dict = None) -> None:
        """Initialize the module."""
        self.name = self.__class__.__name__.lower()
        self._cfg = config or {}

    def remove_duplicates(self, data: List[Dict]):
        """Loop on data and filter out duplicates"""
        filtered = data.copy()
        imdbids = []
        for item in filtered:
            if item.get('imdbid') and item['imdbid'] in imdbids:
                log(f"Item '{item.get('title')}' ({item.get('year')}) [{item.get('imdbid')}] is a duplicate.")
                filtered.remove(item)
            else:
                imdbids.append(item['imdbid'])

        tmdbids = []
        for item in filtered:
            if item.get('tmdbid') and item['tmdbid'] in tmdbids:
                log(f"Item '{item.get('title')}' ({item.get('year')}) [{item.get('tmdbid')}] is a duplicate.")
                filtered.remove(item)
            else:
                tmdbids.append(item['tmdbid'])

        name_years = []
        for item in filtered:
            if item.get('title') and item.get('year') \
                and f"{item['title']} ({item['year']})" in name_years:
                log(f"Item '{item.get('title')}' ({item.get('year')}) is a duplicate.")
                filtered.remove(item)
            else:
                name_years.append(f"{item['title']} ({item['year']})")
        return filtered
