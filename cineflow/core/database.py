"""SQLite-backed cache for media information and requests."""

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
    """Database class for storing media information and request caching."""

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
        """Create the cache schema and migrate legacy media tables when needed."""
        with self._lock:
            try:
                if self._cursor is None or self._conn is None:
                    return
                self._cursor.execute(
                    "CREATE TABLE IF NOT EXISTS request (hash TEXT NOT NULL PRIMARY KEY, "
                    "data BLOB NOT NULL, added REAL NOT NULL);"
                )
                self._conn.commit()
                if not self._table_exists("media"):
                    self._create_media_table("media")
                elif not self._media_has_unique_key():
                    self._migrate_media_table()
                self._conn.commit()
            except (AttributeError, sqlite3.Error) as error:
                log(f"Error creating cache DB tables: {error}", level="WARNING")

    def _table_exists(self, table: str) -> bool:
        """Return whether a named SQLite table exists."""
        if self._cursor is None:
            return False
        self._cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?;", (table,)
        )
        return self._cursor.fetchone() is not None

    def _create_media_table(self, table: str) -> None:
        """Create a media table with the logical cache key enforced."""
        if self._cursor is None:
            return
        self._cursor.execute(
            f"CREATE TABLE {table} (title TEXT NOT NULL, year INTEGER NOT NULL, "
            "kind TEXT NOT NULL, source TEXT NOT NULL, data BLOB NOT NULL, "
            "added REAL NOT NULL, UNIQUE(source, title, year, kind));"
        )

    def _media_has_unique_key(self) -> bool:
        """Return whether media enforces its logical cache key."""
        if self._cursor is None:
            return False
        expected = ["source", "title", "year", "kind"]
        self._cursor.execute("PRAGMA index_list(media);")
        for _, name, unique, *_ in self._cursor.fetchall():
            if unique:
                self._cursor.execute(f"PRAGMA index_info({name});")
                if [row[2] for row in self._cursor.fetchall()] == expected:
                    return True
        return False

    def _migrate_media_table(self) -> None:
        """Replace a legacy media table with a de-duplicated keyed version."""
        if self._cursor is None or self._conn is None:
            return
        try:
            self._cursor.execute("BEGIN IMMEDIATE;")
            self._create_media_table("media_replacement")
            self._cursor.execute(
                "INSERT INTO media_replacement (source, title, year, kind, data, added) "
                "SELECT source, title, year, kind, data, added FROM media AS candidate "
                "WHERE rowid = (SELECT rowid FROM media AS latest WHERE "
                "latest.source = candidate.source AND latest.title = candidate.title AND "
                "latest.year = candidate.year AND latest.kind = candidate.kind "
                "ORDER BY latest.added DESC, latest.rowid DESC LIMIT 1);"
            )
            self._cursor.execute("DROP TABLE media;")
            self._cursor.execute("ALTER TABLE media_replacement RENAME TO media;")
            self._conn.commit()
            log("Migrated legacy media cache table to a unique logical key.")
        except sqlite3.Error:
            self._conn.rollback()
            raise

    def store_media(self, source: str, data: dict[str, Any]) -> None:
        """Store media under its source, title, year, and kind cache key."""
        if not data or not source:
            log(f"Empty data or source cannot store in cache: {data}, {source}")
            return
        if not data.get("title") or not data.get("year") or not data.get("kind"):
            log(f"Invalid data for media cannot store in cache: {data}")
            return
        with self._lock:
            try:
                self._execute_media_upsert(source, data)
                log(f"Added media to cache DB: {data.get('title')} ({data.get('year')})")
            except (AttributeError, sqlite3.Error) as error:
                log(f"Error storing media in cache DB: {error}", level="WARNING")

    def _execute_media_upsert(self, source: str, data: dict[str, Any]) -> None:
        """Execute and commit the media SQLite upsert."""
        if self._cursor is None or self._conn is None:
            raise AttributeError("Cache database is not connected")
        encoded = base64.b64encode(json.dumps(data).encode("utf-8"))
        self._cursor.execute(
            "INSERT INTO media (source, title, year, kind, data, added) VALUES "
            "(?, ?, ?, ?, ?, ?) ON CONFLICT(source, title, year, kind) DO UPDATE SET "
            "data = excluded.data, added = excluded.added;",
            (source, data["title"], data["year"], data["kind"], encoded, dt.now().timestamp()),
        )
        self._conn.commit()

    def get_media(self, source: str, title: str, year: int, kind: str) -> dict[str, Any] | None:
        """Get unexpired media by its logical cache key."""
        with self._lock:
            try:
                if self._cursor is None:
                    return None
                self._cursor.execute(
                    "SELECT data, added FROM media WHERE source = ? AND title = ? "
                    "AND year = ? AND kind = ? ORDER BY added DESC LIMIT 1;",
                    (source, title, year, kind),
                )
                data = self._cursor.fetchone()
            except (AttributeError, sqlite3.Error) as error:
                log(f"Error fetching media from cache DB: {error}", level="WARNING")
                return None
        return self._get_cached_data(data, self._default_expire, f"Media: {title} ({year})")

    def store_request(self, rhash: str, data: dict[str, Any]) -> None:
        """Store request data in the database."""
        if not data or not rhash:
            log(f"Empty data or hash cannot store in cache: {data}, {rhash}")
            return
        with self._lock:
            try:
                if self._cursor is None or self._conn is None:
                    return
                encoded = base64.b64encode(json.dumps(data).encode("utf-8"))
                self._cursor.execute(
                    "INSERT OR REPLACE INTO request (hash, data, added) VALUES (?, ?, ?);",
                    (rhash, encoded, dt.now().timestamp()),
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
        self._table_cleanup("media")
        self._table_cleanup("request")
        log(f"End database cleanup for db '{self._file.name}'")

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            log(f"Database connection closed for '{self._file.name}'")

    def _table_cleanup(self, table: str) -> None:
        """Cleanup old entries from a known cache table."""
        if table not in {"media", "request"}:
            raise ValueError(f"Unknown cache table: {table}")
        with self._lock:
            try:
                if self._cursor is None or self._conn is None:
                    return
                self._cursor.execute(
                    f"DELETE FROM {table} WHERE added < ?;",
                    (dt.now().timestamp() - self._default_expire,),
                )
                self._conn.commit()
            except (AttributeError, sqlite3.Error) as error:
                log(f"Error cleaning up table '{table}': {error}", level="WARNING")
