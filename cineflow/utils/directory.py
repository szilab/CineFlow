"""Directory handler"""

import os
import shutil
import time
import re
import json
from uuid import uuid4
from threading import Lock
from pathlib import Path
from cineflow.utils.image import ImageHandler
from cineflow.core.logger import log
from cineflow.utils.misc import sanitize_path
from cineflow.runtime import export_directory, media_directory


class DirectoryHandler:
    """Directory handler class."""
    DEFAULT_MIN_ITEM_AGE = 30
    DEFAULT_MIN_ITEM_COUNT = 10
    STAGE_PREFIX = '.cineflow-stage-'
    BACKUP_PREFIX = '.cineflow-backup-'
    TRANSACTION_PREFIX = '.cineflow-txn-'
    TRASH_DIRECTORY = '.cineflow-trash'

    def __init__(self, directory: str) -> None:
        """Initialize the directory handler."""
        self._max_item_age = self.DEFAULT_MIN_ITEM_AGE
        self._max_item_count = self.DEFAULT_MIN_ITEM_COUNT
        self._lock = Lock()
        if not directory:
            raise ValueError("Directory name must be provided.")
        self._root = export_directory()
        self._path = self._resolve_library_path(directory)
        if self._path.exists() and not self._path.is_dir():
            raise ValueError(f"Directory path '{self._path}' exists but is not a directory.")
        try:
            self._path.mkdir(parents=True, exist_ok=True)
            if not os.access(self._path, os.W_OK):
                raise ValueError(f"Directory path '{self._path}' is not writable.")
            self._recover_transactions()
        except OSError as e:
            raise ValueError(f"Error creating directory '{self._path}': {e}") from e

    def all(self) -> list:
        """Get the list of items in directory."""
        with self._lock:
            try:
                return [
                    directory for directory in self._path.iterdir()
                    if directory.is_dir() and not self._is_internal_directory(directory)
                ]
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
        """Atomically export metadata to an existing directory."""
        item_path = self._item_path(item)
        with self._lock:
            try:
                if not item_path.exists():
                    log(f"Failed to export data: {item} missing", level='WARNING')
                    return False
                self._write_json(path=item_path / 'data.json', data=media)
                log(f"Data for item '{item}' exported successfully.")
                return True
            except (OSError, ValueError) as e:
                log(f"Failed to export data: {e}", level='WARNING')
        return False

    def publish(
        self, item: str, media: dict, image: ImageHandler = None, resolution: str = None,
    ) -> bool:
        """Publish a complete library item without exposing a partial export."""
        item_path = self._item_path(item)
        with self._lock:
            stage_path = self._path / f"{self.STAGE_PREFIX}{uuid4().hex}"
            try:
                stage_path.mkdir()
                self._write_item(
                    item_path=stage_path,
                    item_name=item_path.name,
                    image=image,
                    resolution=resolution,
                    media=media,
                )
            except (OSError, ValueError) as e:
                self._remove_tree(stage_path)
                log(f"Failed to stage item '{item}': {e}", level='WARNING')
                return False

            if not item_path.exists():
                try:
                    os.replace(stage_path, item_path)
                    self._sync_directory(self._path)
                    log(f"Item '{item}' published successfully.")
                    return True
                except OSError as e:
                    self._remove_tree(stage_path)
                    log(f"Failed to publish item '{item}': {e}", level='WARNING')
                    return False
            return self._replace_item(item_path=item_path, stage_path=stage_path)

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
        """Atomically hide an item before permanently deleting its files."""
        item_path = self._item_path(item)
        with self._lock:
            return self._remove_path(item_path=item_path)

    def cleanup(self) -> None:
        """Synchronously remove items exceeding configured age or count limits."""
        log(f"Start library cleanup for path '{self._path}'")
        with self._lock:
            try:
                dir_list = [
                    item for item in self._path.iterdir()
                    if item.is_dir() and not self._is_internal_directory(item)
                ]
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
                        self._remove_path(item_path=item)
                        continue
                    kept += 1
                except OSError as e:
                    log(f"Failed to clean item '{item}': {e}", level='WARNING')
        log(f"End library cleanup for path '{self._path}'")

    def _write_item(
        self, item_path: Path, item_name: str, image: ImageHandler, resolution: str, media: dict,
    ) -> None:
        """Create all item files in a staging directory."""
        file = re.split(r'[\(\[]', item_name, maxsplit=1)[0].strip() + '.mkv'
        media_dir = self._media_directory()
        if media_dir and self._copy_sample(
            file_path=item_path / file, media_dir=media_dir, resolution=resolution,
        ):
            log(f"Media file for item '{item_name}' created from sample ({resolution or 'default'}).")
        else:
            Path(item_path / file).touch(exist_ok=True)
            log(f"Media file for item '{item_name}' created as placeholder.")
        self._sync_file(item_path / file)
        if image:
            image.save(str(item_path))
            self._sync_file(item_path / image.filename)
            log(f"Image for item '{item_name}' saved successfully.")
        self._write_json(path=item_path / 'data.json', data=media)

    def _replace_item(self, item_path: Path, stage_path: Path) -> bool:
        """Swap an existing item with a staged replacement and recover on restart."""
        transaction_id = uuid4().hex
        backup_path = self._path / f"{self.BACKUP_PREFIX}{transaction_id}"
        transaction_path = self._path / f"{self.TRANSACTION_PREFIX}{transaction_id}.json"
        transaction = {
            'item': item_path.name,
            'stage': stage_path.name,
            'backup': backup_path.name,
            'state': 'prepared',
        }
        try:
            self._write_json(path=transaction_path, data=transaction)
            os.replace(item_path, backup_path)
            self._sync_directory(self._path)
            transaction['state'] = 'old_moved'
            self._write_json(path=transaction_path, data=transaction)
            os.replace(stage_path, item_path)
            self._sync_directory(self._path)
            transaction['state'] = 'published'
            self._write_json(path=transaction_path, data=transaction)
            self._remove_tree(backup_path)
            transaction_path.unlink(missing_ok=True)
            self._sync_directory(self._path)
            log(f"Item '{item_path.name}' published successfully.")
            return True
        except OSError as e:
            log(f"Failed to publish item '{item_path.name}': {e}", level='WARNING')
            return False

    def _recover_transactions(self) -> None:
        """Recover interrupted directory swaps before exposing the library."""
        for transaction_path in self._path.glob(f"{self.TRANSACTION_PREFIX}*.json"):
            try:
                transaction = json.loads(transaction_path.read_text(encoding='utf-8'))
                names = [transaction.get(key, '') for key in ('item', 'stage', 'backup')]
                if not all(name and Path(name).name == name for name in names):
                    raise ValueError('invalid transaction paths')
                item_path, stage_path, backup_path = (self._path / name for name in names)
                state = transaction.get('state')
                if item_path.exists():
                    self._remove_tree(stage_path)
                    self._remove_tree(backup_path)
                elif state == 'old_moved' and stage_path.exists():
                    os.replace(stage_path, item_path)
                    self._remove_tree(backup_path)
                elif backup_path.exists():
                    os.replace(backup_path, item_path)
                    self._remove_tree(stage_path)
                else:
                    raise ValueError('missing item, stage, and backup')
                transaction_path.unlink(missing_ok=True)
                self._sync_directory(self._path)
                log(f"Recovered interrupted library export for '{item_path.name}'.")
            except (OSError, ValueError, json.JSONDecodeError) as e:
                log(f"Failed to recover library transaction '{transaction_path.name}': {e}", level='WARNING')
        for stage_path in self._path.glob(f"{self.STAGE_PREFIX}*"):
            self._remove_tree(stage_path)

    def _remove_path(self, item_path: Path) -> bool:
        """Move an item out of the visible library before deletion."""
        if not item_path.exists():
            return False
        trash_path = self._path / self.TRASH_DIRECTORY
        pending_delete = trash_path / f"{item_path.name}-{uuid4().hex}"
        try:
            trash_path.mkdir(exist_ok=True)
            os.replace(item_path, pending_delete)
            self._sync_directory(self._path)
            self._remove_tree(pending_delete)
            log(f"Item '{item_path.name}' removed successfully from library.", level='MSG')
            return True
        except OSError as e:
            log(f"Failed to remove '{item_path.name}': {e}", level='WARNING')
            return False

    @staticmethod
    def _remove_tree(path: Path) -> None:
        """Remove an internal staging, backup, or trash directory when present."""
        if path.exists():
            shutil.rmtree(path)

    @staticmethod
    def _is_internal_directory(directory: Path) -> bool:
        """Return whether a directory is internal publish or deletion state."""
        return directory.name == DirectoryHandler.TRASH_DIRECTORY or directory.name.startswith((
            DirectoryHandler.STAGE_PREFIX,
            DirectoryHandler.BACKUP_PREFIX,
        ))

    @staticmethod
    def _sync_directory(path: Path) -> None:
        """Best-effort durability sync for directory entry changes."""
        DirectoryHandler._sync_path(path=path)

    @staticmethod
    def _sync_file(path: Path) -> None:
        """Best-effort durability sync for staged item content."""
        DirectoryHandler._sync_path(path=path)

    @staticmethod
    def _sync_path(path: Path) -> None:
        """Best-effort sync for a file or directory."""
        try:
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError:
            pass

    def _write_json(self, path: Path, data: dict) -> None:
        """Write JSON through an atomic replacement in the same directory."""
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open('w', encoding='utf-8') as stream:
                json.dump(data, stream, indent=4)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            self._sync_directory(path.parent)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise

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
        media_path = media_directory()
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
