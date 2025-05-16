"""This module provides a class to handle directories."""

from system.logger import log
from system.image import ImageHandler
from bases.data import MediaData
from bases.module import LibraryBase


class LibraryData(MediaData):  # pylint: disable=too-few-public-methods
    """Library data."""

    def __init__(self, **kwargs) -> None:
        self.folder = ''
        self.image = ''
        super().__init__(**kwargs)

class Library(LibraryBase):
    """
    Module to handle media library.

    Configuration:
        - path: path to the media library (required)
        - limit: number of maximum items in library (default: 50)

    Functions:
        - put: import media to the library
        - find: find media in the library
    """

    def __init__(self, config: dict = {}) -> None:  # pylint: disable=dangerous-default-value
        """Initialize the library module."""
        super().__init__(config=config)

    def put(self, data: list) -> None:
        """Import the media to the library."""
        self.ready()
        if not self._ready:
            return
        for item in data or []:
            if not isinstance(item, dict):
                continue
            if not item.get('title') or not item.get('year'):
                log(f"Invalid item: {item}", level='WARNING')
                continue
            self._handler.make(
                directory=f"{item['title']} ({item['year']})",
                file=f"{item.get('title')}.mkv"
            )
            if not item.get('poster'):
                log(f"Item '{item['title']}' has no poster.", level='DEBUG')
                continue
            img = ImageHandler(url=item.get('poster'))
            img.save(
                path=self._handler.path,
                directory=self._handler.fix(f"{item['title']} ({item['year']})")
            )
            log(f"Item '{item['title']}' imported successfully.", level='DEBUG')
        self.cleanup()
