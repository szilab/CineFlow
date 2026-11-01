"""SQLite-backed cache for HTTP request responses."""

import base64
import json
import os
import sqlite3
import tempfile
import threading
from datetime import datetime as dt
from pathlib import Path
from typing import Any

from cineflow.core.bases.singleton import SingletonMeta
from cineflow.core.bases.worker import WorkerBase
from cineflow.core.logger import log


class Database(WorkerBase, metaclass=SingletonMeta):
    """Database class for request response caching."""

    def __init__(self) -> None:
        super().__init__()
        self.delay = 240
        self._file = Path(os.environ.get("DB_DIRECTORY", tempfile.gettempdir()), "cachedb.sqlite3")
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._cursor: sqlite3.Cursor | None = None
        self._default_expire = int(os.environ.get("CACHE_EXPIRE", "86400"))
        try:
            self._conn = sqlite3.connect(self._file, check_same_thread=False)
            self._cursor = self._conn.cursor()
            self.create_tables()
        except sqlite3.Error as error:
            log(f"Cache database connection error cache database not usable: {error}", level="WARNING")
        log(f"Cache database initialized with file '{self._file.name}'")
        self.start()

    def create_tables(self) -> None:
        """Create the request cache schema."""
        with self._lock:
            try:
                if self._cursor is None or self._conn is None:
                    return
                self._cursor.execute(
                    "CREATE TABLE IF NOT EXISTS request (hash TEXT NOT NULL PRIMARY KEY, "
                    "data BLOB NOT NULL, added REAL NOT NULL, expire REAL);"
                )
                self._conn.commit()
            except (AttributeError, sqlite3.Error) as error:
                log(f"Error creating cache DB tables: {error}", level="WARNING")

    def store_request(self, rhash: str, data: Any, expire: int | None = None) -> None:
        """Store request data in the database, kept for ``expire`` seconds."""
        if data is None or not rhash:
            log(f"Empty data or hash cannot store in cache: {data}, {rhash}")
            return
        with self._lock:
            try:
                if self._cursor is None or self._conn is None:
                    return
                encoded = base64.b64encode(json.dumps(data).encode("utf-8"))
                self._cursor.execute(
                    "INSERT OR REPLACE INTO request (hash, data, added, expire) VALUES (?, ?, ?, ?);",
                    (rhash, encoded, dt.now().timestamp(), expire),
                )
                self._conn.commit()
            except (AttributeError, sqlite3.Error) as error:
                log(f"Error storing request in cache DB: {error}", level="WARNING")

    def get_request(self, rhash: str, expire: int | None = None) -> dict[str, Any] | None:
        """Get unexpired request data by hash."""
        with self._lock:
            try:
                if self._cursor is None:
                    return None
                self._cursor.execute("SELECT data, added FROM request WHERE hash = ?;", (rhash,))
                data = self._cursor.fetchone()
            except (AttributeError, sqlite3.Error) as error:
                log(f"Error fetching request from cache DB: {error}", level="WARNING")
                return None
        return self._get_cached_data(data, expire or self._default_expire, f"Request: {rhash}")

    def _get_cached_data(
        self, data: tuple[bytes, float] | None, expire: int, label: str
    ) -> dict[str, Any] | None:
        """Decode an unexpired cache row."""
        if not data:
            log(f"{label} not found in cache DB")
            return None
        if data[1] + expire < dt.now().timestamp():
            log(f"{label} expired in cache DB")
            return None
        return json.loads(base64.b64decode(data[0]).decode("utf-8"))

    def run(self) -> None:
        """Run the database cleanup."""
        log(f"Start database cleanup for db '{self._file.name}'")
        self._request_cleanup()
        log(f"End database cleanup for db '{self._file.name}'")

    def close(self) -> bool:
        """Close the database connection when its cleanup worker has terminated."""
        if self._thread is not None and not self.stop():
            log(
                f"Database cleanup worker for '{self._file.name}' is still running; "
                "connection left open.", level="WARNING"
            )
            return False
        if self._conn:
            self._conn.close()
            self._conn = None
            self._cursor = None
            log(f"Database connection closed for '{self._file.name}'")
        return True

    def _request_cleanup(self) -> None:
        """Remove request cache entries past their own or the default expiry."""
        with self._lock:
            try:
                if self._cursor is None or self._conn is None:
                    return
                self._cursor.execute(
                    "DELETE FROM request WHERE added + COALESCE(expire, ?) < ?;",
                    (self._default_expire, dt.now().timestamp()),
                )
                self._conn.commit()
            except (AttributeError, sqlite3.Error) as error:
                log(f"Error cleaning up request cache: {error}", level="WARNING")
