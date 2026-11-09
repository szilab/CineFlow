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
from cineflow.core.bases.worker import WorkerBase
from cineflow.core.logger import log
from cineflow.utils.misc import sanitize_path
from cineflow.runtime import export_directory
from cineflow.utils.video import placeholder_video, release_profile


class DirectoryHandler:
    """Directory handler class."""
    DEFAULT_MIN_ITEM_AGE = 30
    DEFAULT_MIN_ITEM_COUNT = 10
    STAGE_PREFIX = '.cineflow-stage-'
    BACKUP_PREFIX = '.cineflow-backup-'
    TRANSACTION_PREFIX = '.cineflow-txn-'
    TRASH_DIRECTORY = '.cineflow-trash'
    _locks: dict[Path, Lock] = {}
    _locks_guard = Lock()

    def __init__(self, directory: str, root: Path | None = None) -> None:
        """Initialize the handler of a library folder inside the export root (default: EXPORT_DIRECTORY)."""
        self._max_item_age = self.DEFAULT_MIN_ITEM_AGE
        self._max_item_count = self.DEFAULT_MIN_ITEM_COUNT
        if not directory:
            raise ValueError("Directory name must be provided.")
        self._root = Path(root) if root else export_directory()
        self._path = self._resolve_library_path(directory)
        # every handler of the same directory shares one lock
        with DirectoryHandler._locks_guard:
            self._lock = DirectoryHandler._locks.setdefault(self._path, Lock())
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

    def publish(
        self, item: str, media: dict, image: ImageHandler = None, resolution: str = None,
        kind: str = 'movie',
    ) -> bool:
        """Publish a complete library item without exposing a partial export.

        A ``tv`` item gets a ``Season NN`` folder with one placeholder episode,
        so media servers recognize it as a series.
        """
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
                    kind=kind,
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
        kind: str = 'movie',
    ) -> None:
        """Create all item files in a staging directory."""
        file = re.split(r'[\(\[]', item_name, maxsplit=1)[0].strip()
        if kind == 'tv':
            season = self._season_number(media.get('season'))
            (item_path / f"Season {season:02d}").mkdir()
            file = f"Season {season:02d}/{file} S{season:02d}E01"
        file += '.mkv'
        video = placeholder_video(release_profile(media.get('torrent'), resolution))
        (item_path / file).write_bytes(video)
        log(f"Media file for item '{item_name}' written from the release metadata.")
        # Jellyfin derives "Date added" from the video file's timestamps and only
        # re-reads it when the modification time changes. Stamping the publish
        # time moves new and upgraded items to the front and nothing else.
        os.utime(item_path / file)
        self._sync_file(item_path / file)
        if image:
            image.save(str(item_path))
            self._sync_file(item_path / image.filename)
            log(f"Image for item '{item_name}' saved successfully.")
        self._write_json(path=item_path / 'data.json', data=media)

    @staticmethod
    def _season_number(value) -> int:
        """Return a valid season number for the placeholder episode."""
        try:
            return min(max(int(value), 0), 99)
        except (TypeError, ValueError):
            return 1

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
            raise ValueError("Directory must be inside the export directory.") from exc
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

    @property
    def path(self) -> Path:
        """Return the resolved library directory."""
        return self._path

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


class DirectoryCleaner(WorkerBase):
    """Background worker that applies the age and count limits of one library directory."""

    DELAY = 60  # minutes between cleanups

    def __init__(self, handler: DirectoryHandler) -> None:
        super().__init__()
        self.name = handler.path.name
        self.handler = handler
        self.delay = self.DELAY

    def run(self) -> None:
        """Clean up the library directory."""
        self.handler.cleanup()

    def worker(self) -> None:
        """Wait one period before each cleanup so startup never deletes items."""
        while self._running:
            if self._stop_event.wait(timeout=self._delay * 60):
                break
            try:
                self.run()
            except Exception as exc:  # pylint: disable=broad-except
                log(f"Worker '{self.name}' failed: {exc}", level='ERROR')


class CleanupScheduler:
    """Owns the background cleanup workers of all library directories."""

    _workers: dict[Path, DirectoryCleaner] = {}
    _lock = Lock()

    @classmethod
    def schedule(cls, handler: DirectoryHandler) -> DirectoryCleaner:
        """Start the cleanup of a directory once; later handlers update its limits."""
        with cls._lock:
            worker = cls._workers.get(handler.path)
            if worker is None:
                worker = DirectoryCleaner(handler=handler)
                cls._workers[handler.path] = worker
                worker.start()
            else:
                worker.handler = handler
            return worker

    def stop(self) -> bool:
        """Stop all cleanup workers and report whether they terminated."""
        with self._lock:
            workers = list(self._workers.items())
        stopped = True
        for path, worker in workers:
            if worker.stop():
                with self._lock:
                    self._workers.pop(path, None)
            else:
                stopped = False
        return stopped

    def close(self) -> bool:
        """Report whether every cleanup worker has terminated."""
        return self.stop()
