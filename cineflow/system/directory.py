"""Directory handler"""

import os
import shutil
import time
import re
import platform
from pathlib import Path
from cineflow.system.image import ImageHandler
from cineflow.system.logger import log
from cineflow.system.misc import sanitize_name
from cineflow.bases.worker import WorkerBase


class DirectoryHandler(WorkerBase):
    """Directory handler class."""
    DEFAULT_MIN_ITEM_AGE = 30
    DEFAULT_MIN_ITEM_COUNT = 10

    def __init__(self, directory: str) -> None:
        """Initialize the directory handler."""
        super().__init__()
        self._max_item_age = self.DEFAULT_MIN_ITEM_AGE
        self._max_item_count = self.DEFAULT_MIN_ITEM_COUNT
        if not directory:
            raise ValueError("Directory name must be provided.")
        self._path = Path(os.environ.get("EXPORT_DIRECTORY", "/library")).resolve() / directory
        if self._path.exists() and not self._path.is_dir():
            raise ValueError(f"Directory path '{self._path}' exists but is not a directory.")
        try:
            self._path.mkdir(parents=True, exist_ok=True)
            if not os.access(self._path, os.W_OK):
                raise ValueError(f"Directory path '{self._path}' is not writable.")
        except OSError as e:
            raise ValueError(f"Error creating directory '{self._path}': {e}") from e
        self.start()

    def all(self) -> list:
        """Get the list of items in directory."""
        try:
            directories = []
            for d in self._path.iterdir():
                if d.is_dir():
                    directories.append(d)
            return directories
        except OSError as e:
            log(f"Error listing items: {e}", level='WARNING')
        return []

    def make(self, item: str, image: ImageHandler = None) -> bool:
        """Make an item and file."""
        item = sanitize_name(item)
        file = re.split(r'[\(\[]', item, maxsplit=1)[0].strip() + '.mkv'
        try:
            if not Path.exists(self._path / item):
                os.makedirs(self._path / item, exist_ok=True)
                log(f"Item '{item}' created successfully.")
            Path(self._path / item / file).touch(exist_ok=True)
            if image:
                image.save(str(self._path / item))
                log(f"Image for item '{item}' saved successfully.")
            return True
        except (OSError, ValueError) as e:
            log(f"Failed to create: {e}", level='WARNING')
        return False

    def remove(self, item: str) -> bool:
        """Remove an item."""
        item = sanitize_name(item)
        try:
            shutil.rmtree(self._path / item)
            log(f"Item '{item}' removed successfully.")
            return True
        except OSError as e:
            log(f"Failed to removing: {e}", level='WARNING')
        return False

    def run(self):
        """Run method for WorkerBase to run libraray cleanup periodicly."""
        log(f"Start library cleanup for path '{self._path}'")
        if not (dir_list := self.all()):
            return
        # Sort by creation time, newest first
        dir_list.sort(key=lambda x: Path(x).stat().st_ctime, reverse=True)
        i = 1
        for item in dir_list:
            try:
                # Remove the item if it exceeds the maximum count for the directory
                if i > self.max_item_count:
                    log(f"Found excess item: {item}")
                    self.remove(item)
                    continue
                # Check if the item is older than the maximum age
                file_age = time.time() - Path(self._path / item).stat().st_ctime
                if file_age > self.max_item_age * 24 * 60 * 60:
                    log(f"Found old item: {item}")
                    self.remove(item)
                    continue
                i += 1
            except OSError as e:
                log(f"Failed to clean item '{item}': {e}", level='WARNING')
                continue
        log(f"End library cleanup for path '{self._path}'")

    @property
    def max_item_age(self) -> int:
        return self._max_item_age

    @max_item_age.setter
    def max_item_age(self, value: int) -> None:
        self._max_item_age = max(value, self.DEFAULT_MIN_ITEM_AGE)

    @property
    def max_item_count(self) -> int:
        return self._max_item_count

    @max_item_count.setter
    def max_item_count(self, value: int) -> None:
        self._max_item_count = max(value, self.DEFAULT_MIN_ITEM_COUNT)
