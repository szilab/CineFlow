"""This module provides a class to handle directories."""

from typing import List, Dict
from PIL import Image
from cineflow.system.logger import log
from cineflow.system.misc import evaluate
from cineflow.system.image import ImageHandler
from cineflow.bases.module import LibraryBase


class Library(LibraryBase):
    """
    Module to handle media library.

    Configuration:
        - path: path to the media library (required)
        - limit: number of maximum items in library (default: 50)
        - age: maximum age of items in library in days (default: 30)

    Functions:
        - put: import media to the library
        - find: find media in the library
    """

    def __init__(self, config: dict = None) -> None:
        """Initialize the library module."""
        super().__init__(config=config, required=['directory'])
        self.mappings = {
            'directory': ['directory'],
            'title': ['directory'],
            'year': ['directory'],
            'tmdbid': ['directory'],
        }
        self.transforms = {
            'title': lambda x: x.split(' (')[0].strip(),
            'year': lambda x: x.split(' (')[1].split(')')[0],
            'tmdbid': self._get_tmdbid,
        }

    def get(self) -> List[Dict]:
        """Get the list of items in the library."""
        results = []
        directories = self._handler.all()
        for directory in directories:
            if '(' not in directory.name or ')' not in directory.name:
                log(f"Item '{directory.name}' does not have a valid name format.", level='WARNING')
                continue
            results.append({'directory': directory.name})
        log(f"Items in library: '{len(results)}'")
        return [self.map(item=item) for item in results]

    def put(self, data: List[Dict]) -> List[Dict]:
        """Import the media to the library."""
        for media in data or []:
            item = self._item_name(media=media)
            if media.get('poster'):
                image = self._create_poster(media=media)
            else:
                image = None
                log(f"Item '{media['title']}' has no poster.", level='WARNING')
            if self._handler.make(item=item, image=image):
                media['directory'] = item
        return data

    def remove(self, data: List[Dict]) -> None:
        """Remove the media from the library."""
        for media in data or []:
            item = self._item_name(media=media)
            self._handler.remove(item=item)

    def _item_name(self, media: dict) -> str:
        """Generate a library item name for the media."""
        if media.get('tmdbid'):
            return media['title'] + " (" + str(media['year']) + f") [tmdbid-{media['tmdbid']}]"
        return media['title'] + " (" + str(media['year']) + ")"

    def _get_tmdbid(self, directory: dict) -> str:
        """Extract TMDB ID from the directory name."""
        if '[tmdbid-' in directory and ']' in directory:
            return directory.split('[tmdbid-')[1].replace(']', '').strip()
        return None

    def _create_poster(self, media: dict) -> Image.Image:
        """Create a poster for the item."""
        img = ImageHandler(url=media.get('poster'))
        if not img:
            log(f"Failed to load image for item '{media['title']}'.")
            return None
        if not self.cfg('rules'):
            log("No modification rules to apply to the library images.")
            return None
        for rule in self.cfg('rules'):
            if not isinstance(rule, dict) or not rule.get('property'):
                log(f"Invalid library modification: {rule}", level='WARNING')
                continue
            if evaluate(
                left=media.get(rule.get('property')),
                right=rule.get('value'),
                expression=rule.get('expression', 'exists'),
                wcase=rule.get('case_sensitive', True)
            ):
                img.apply_from_rule(rule=rule)
        return img
