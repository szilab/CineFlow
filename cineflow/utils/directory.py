"""Directory handler"""

import os
import shutil
import time
import re
import json
from threading import Lock
from pathlib import Path
from cineflow.utils.image import ImageHandler
from cineflow.core.logger import log
from cineflow.utils.misc import sanitize_path


class DirectoryHandler:
    """Directory handler class."""
    DEFAULT_MIN_ITEM_AGE = 30
    DEFAULT_MIN_ITEM_COUNT = 10

    def __init__(self, directory: str) -> None:
        """Initialize the directory handler."""
        self._max_item_age = self.DEFAULT_MIN_ITEM_AGE
        self._max_item_count = self.DEFAULT_MIN_ITEM_COUNT
        self._lock = Lock()
        if not directory:
            raise ValueError("Directory name must be provided.")
        self._root = Path(os.environ.get("EXPORT_DIRECTORY", "/library")).resolve()
        self._path = self._resolve_library_path(directory)
        if self._path.exists() and not self._path.is_dir():
            raise ValueError(f"Directory path '{self._path}' exists but is not a directory.")
        try:
            self._path.mkdir(parents=True, exist_ok=True)
            if not os.access(self._path, os.W_OK):
                raise ValueError(f"Directory path '{self._path}' is not writable.")
        except OSError as e:
            raise ValueError(f"Error creating directory '{self._path}': {e}") from e

    def all(self) -> list:
        """Get the list of items in directory."""
        with self._lock:
            try:
                return [directory for directory in self._path.iterdir() if directory.is_dir()]
            except OSError as e:
                log(f"Error listing items: {e}", level='WARNING')
        return []

    def make(self, item: str, image: ImageHandler = None, resolution: str = None) -> bool:
        """Make an item and file."""
        item_path = self._item_path(item)
        item = item_path.name
        file = re.split(r'[\(\[]', item, maxsplit=1)[0].strip() + '.mkv'
        with self._lock:
            try:
                if not item_path.exists():
                    os.makedirs(item_path, exist_ok=True)
                    log(f"Item '{item}' created successfully.")
                media_dir = self._media_directory()
                if media_dir and self._copy_sample(
                    file_path=item_path / file, media_dir=media_dir, resolution=resolution
                ):
                    log(f"Media file for item '{item}' created from sample ({resolution or 'default'}).")
                else:
                    Path(item_path / file).touch(exist_ok=True)
                    log(f"Media file for item '{item}' created as placeholder.")
                if image:
                    image.save(str(item_path))
                    log(f"Image for item '{item}' saved successfully.")
                return True
            except (OSError, ValueError) as e:
                log(f"Failed to create: {e}", level='WARNING')
        return False

    def exists(self, item: str) -> bool:
        """Check if item exists."""
        item_path = self._item_path(item)
        with self._lock:
            try:
                if item_path.exists():
                    return True
            except (OSError, ValueError) as e:
                log(f"Failed to check existence: {e}", level='WARNING')
        return False

    def export(self, item: str, media: dict) -> bool:
        """Export data to directory."""
        item_path = self._item_path(item)
        with self._lock:
            try:
                if not item_path.exists():
                    log(f"Failed to export data: {item} missing", level='WARNING')
                with open(item_path / 'data.json', 'w', encoding='utf-8') as f:
                    json.dump(media, f, indent=4)
                log(f"Data for item '{item}' exported successfully.")
                return True
            except (OSError, ValueError) as e:
                log(f"Failed to export data: {e}", level='WARNING')
        return False

    def imprt(self, item: str) -> dict:
        """Import data from directory."""
        item_path = self._item_path(item)
        with self._lock:
            try:
                if not item_path.exists():
                    log(f"Failed to import data: {item} missing", level='WARNING')
                with open(item_path / 'data.json', 'r', encoding='utf-8') as f:
                    media = json.load(f)
                log(f"Data for item '{item}' imported successfully.")
                return media
            except (OSError, ValueError) as e:
                log(f"Failed to import data: {e}", level='DEBUG')
        return {}

    def remove(self, item: str) -> bool:
        """Remove an item."""
        item_path = self._item_path(item)
        with self._lock:
            try:
                shutil.rmtree(item_path)
                log(f"Item '{item}' removed successfully from library.", level='MSG')
                return True
            except OSError as e:
                log(f"Failed to removing: {e}")
        return False

    def cleanup(self) -> None:
        """Synchronously remove items exceeding configured age or count limits."""
        log(f"Start library cleanup for path '{self._path}'")
        with self._lock:
            try:
                dir_list = [item for item in self._path.iterdir() if item.is_dir()]
                dir_list.sort(key=lambda item: item.stat().st_ctime, reverse=True)
            except OSError as e:
                log(f"Error listing items for cleanup: {e}", level='WARNING')
                return
            kept = 0
            for item in dir_list:
                try:
                    file_age = time.time() - item.stat().st_ctime
                    if kept >= self.max_item_count or file_age > self.max_item_age * 86400:
                        log(f"Found expired or excess item: {item}")
                        shutil.rmtree(item)
                        continue
                    kept += 1
                except OSError as e:
                    log(f"Failed to clean item '{item}': {e}", level='WARNING')
        log(f"End library cleanup for path '{self._path}'")

    def _resolve_library_path(self, directory: str) -> Path:
        """Resolve a configured library path within the export root."""
        path = Path(directory)
        target = path.resolve() if path.is_absolute() else (self._root / path).resolve()
        try:
            target.relative_to(self._root)
        except ValueError as exc:
            raise ValueError("Directory must be inside EXPORT_DIRECTORY.") from exc
        return target

    def _item_path(self, item: str | Path) -> Path:
        """Resolve an item path without permitting escape from the library."""
        raw_path = Path(item)
        candidate = raw_path.resolve() if raw_path.is_absolute() else (self._path / raw_path).resolve()
        try:
            relative = candidate.relative_to(self._path)
        except ValueError as exc:
            raise ValueError("Item path must be inside the configured library.") from exc
        target = (self._path / sanitize_path(str(relative))).resolve()
        try:
            target.relative_to(self._path)
        except ValueError as exc:
            raise ValueError("Item path must be inside the configured library.") from exc
        return target

    def _media_directory(self) -> Path | None:
        """Get the media sample directory path."""
        # Try environment variable first
        media_path = Path(os.environ.get("MEDIA_DIRECTORY", "/app/media"))
        if media_path.exists() and media_path.is_dir():
            sample_files = list(media_path.glob("sample.*.mp4"))
            if sample_files:
                return media_path
            log(f"Media directory '{media_path}' exists but no sample files found.", level='DEBUG')
        else:
            log(f"Media directory '{media_path}' not found.", level='DEBUG')
        return None

    def _copy_sample(self, file_path: Path, media_dir: Path, resolution: str = None) -> bool:
        """Copy a sample file matching the resolution to the destination path."""
        source = media_dir / f"sample.{resolution}.mp4"
        if source.exists():
            shutil.copy2(str(source), str(file_path))
            return True
        log(f"No exact sample match for resolution '{resolution}'.", level='DEBUG')
        return False

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
