import time
from pathlib import Path
from system.logger import log
from handlers.file import FileHandler


class LibraryHandler():
    def __init__(self, path: str, limit: int = 30, retention: int = 90, type: str = 'movie') -> None:
        self._path = Path(path)
        self._retention = retention
        self._limit = limit
        self._fh = FileHandler(base_path=path)
        self._items = []
        self._type = type
        self.__initialize_library()

    def type(self) -> str:
        """Get the type of the library."""
        return self._type

    def exists(self, item: str) -> bool:
        """
        Check if an item exists in the library.
        :param item: The item to check for.
        """
        return item in self._items

    def get(self, item: str = None) -> Path:
        """
        Get an item or list all items if item empty.
        :param item: The item to get.
        """
        if item:
            return [i for i in self._items if i == item]
        return self._items

    def add(self, item: str, metadata: dict) -> None:
        """
        Add a new item to the library.
        :param item: The item to add.
        :param metadata: The metadata for the item.
        """
        # Check if item exists or limit reached
        if self.exists(item) or self.__limit_reached():
            return False
        # Create item directory and add metadata
        self._fh.create_directory(item)
        self._fh.add_file(item=item, file_name="metadata.json", content=metadata)
        self._fh.add_file(item=item, file_name=f"{item.replace(' ', '_')}.mkv")
        self.__refresh_items()
        return bool(item in self._items)

    def update(self, item: str, metadata: dict) -> None:
        """
        Update the metadata for an item in the library.
        :param item: The item to update.
        :param metadata: The metadata for the item.
        """
        self._fh.add_file(item=item, file_name="metadata.json", content=metadata)

    # def add_cover(self, item: str, image_path: str, metadata: dict = {}) -> None:
    #     """Add a cover image to a directory."""
    #     if not image_path:
    #         log(f"Missing cover image path for item: {item}", level='WARNING')
    #         return
    #     out_dir = f"{self._path}/{item}"
    #     self.ih.apply(path=image_path, directory=out_dir, name="cover", metadata=metadata)

    def metadataof(self, item: str) -> dict:
        """
        Get the metadata for an item in the library.
        :param item: The item to get metadata for.
        """
        data = self._fh.get_file(item=item, file_name="metadata.json", typeof="json")
        return data

    def remove(self, item: str) -> None:
        """
        Remove an item from the library.
        :param item: The item to remove.
        """
        self._fh.remove_directory(item=item)
        self.__refresh_items()

    def cleanup(self) -> None:
        """
        Remove items older than a specified number of days.
        """
        # Calculate cutoff time
        cutoff = time.time() - (self._retention * 86400)
        # Remove old items
        for item in self._items:
            item_path = self._path / item
            if item_path.stat().st_birthtime < cutoff:
                log(f"Removing old item: {item}")
                self._fh.remove_directory(item)
        self.__refresh_items()

    # def add_image(self, item: str, metadata: dict) -> None:
    #     """Add an image to an item in the library."""
    #     if item not in self._items:
    #         self._fh.create_directory(item)
    #         self.__refresh_items()
    #     self.im.add_image(folder_name, url, name, mode)

    def __initialize_library(self) -> None:
        if not self._path.exists():
            log(f"Initializing library: {self._path}")
            self._path.mkdir(parents=True)
        self.__refresh_items()

    def __refresh_items(self) -> None:
        self._items = [f.name for f in self._path.iterdir() if f.is_dir()]

    def __limit_reached(self):
        if len(self._items) >= self._limit:
            log(f"Library item limit reached: {self._limit}", level='DEBUG')
            return True
        return False
