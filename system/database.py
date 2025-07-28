"""Database module for storing media information"""

import os
import threading
import sqlite3
import json
import base64
from datetime import datetime as dt
from system.logger import log
from bases.singleton import SingletonMeta
from bases.worker import WorkerBase


class Database(WorkerBase, metaclass=SingletonMeta):
    # TO-DO: Add matedate refresh based on added time
    """Database class for storing media information and request caching."""

    def __init__(self):
        super().__init__()
        self._file = os.path.join(os.environ.get("DATA_DIRECTORY" ,"/data"), "db.sqlite3")
        self._lock = threading.Lock()
        self._conn = None
        self._cursor = None
        self._default_expire = int(os.environ.get("CACHE_EXPIRE", "86400"))
        try:
            self._conn = sqlite3.connect(self._file, check_same_thread=False)
            self._cursor = self._conn.cursor()
            self.create_tables()
        except sqlite3.Error as e:
            log(f"Cache database connection error cache database not usable: {e}", level="WARNING")
        log(f"Cache database initialized with file '{os.path.basename(self._file)}'")
        self.start()

    def create_tables(self):
        """Create tables in database"""
        if os.path.getsize(self._file) == 0:
            log("Creating cache DB tables.")
            with self._lock:
                try:
                    self._cursor.execute("""
                        CREATE TABLE IF NOT EXISTS media (
                            title TEXT NOT NULL,
                            year INTEGER NOT NULL,
                            kind TEXT NOT NULL,
                            source TEXT NOT NULL,
                            data BLOB NOT NULL,
                            added REAL NOT NULL
                        );
                    """.strip())
                    self._conn.commit()
                    self._cursor.execute("""
                        CREATE TABLE IF NOT EXISTS request (
                            hash TEXT NOT NULL PRIMARY KEY,
                            data BLOB NOT NULL,
                            added REAL NOT NULL
                        );
                    """.strip())
                    self._conn.commit()
                    log("Cache DB tables created successfully.")
                except (AttributeError, sqlite3.Error) as e:
                    log(f"Error creating cache DB tables: {e}", level="WARNING")

    def store_media(self, source: str, data: dict) -> None:
        """Add movie to the database"""
        if not data or not source:
            log(f"Empty data or source cannot store in cache: {data}, {source}")
            return
        if not data.get('title') or not data.get('year') or not data.get('kind'):
            log(f"Invalid data for media cannot store in cache: {data}")
            return
        with self._lock:
            bytes_data = base64.b64encode(bytes(json.dumps(data), "utf-8"))
            try:
                self._cursor.execute(
                    "INSERT OR REPLACE INTO media (source, title, year, kind, data, added) VALUES (?, ?, ?, ?, ?, ?);",
                    (source, data.get('title'), data.get('year'), data.get('kind'), bytes_data, dt.now().timestamp(),)
                )
                self._conn.commit()
                log(f"Added media to cache DB: {data.title} ({data.year})")
            except (AttributeError, sqlite3.Error) as e:
                log(f"Error storing media in cache DB: {e}", level="WARNING")

    def get_media(self, source: str, title: str, year: int, kind: str, expire: int = None) -> dict:
        """Get movie by title"""
        with self._lock:
            try:
                self._cursor.execute(
                    "SELECT data,added FROM media WHERE source = ? AND title = ? AND year = ? AND kind = ?;",
                    (source, title, year, kind,)
                )
                data = self._cursor.fetchone()
            except (AttributeError, sqlite3.Error) as e:
                log(f"Error fetching media from cache DB: {e}", level="WARNING")
                return None
            if not data:
                log(f"Media not found in cache DB: {title} ({year})")
                return None
            if not expire:
                expire = self._default_expire
            if data[1] + expire < dt.now().timestamp():
                log(f"Media expired in cache DB: {title} ({year})")
                return None
            return json.loads(base64.b64decode(data[0]).decode("utf-8"))

    def store_request(self, rhash: str, data: dict) -> None:
        """Store request data in the database."""
        if not data or not rhash:
            log(f"Empty data or hash cannot store in cache: {data}, {rhash}")
            return
        with self._lock:
            bytes_data = base64.b64encode(bytes(json.dumps(data), "utf-8"))
            try:
                self._cursor.execute(
                    "INSERT OR REPLACE INTO request (hash, data, added) VALUES (?, ?, ?);",
                    (rhash, bytes_data, dt.now().timestamp(),)
                )
                self._conn.commit()
                log(f"Added request to cache DB: {rhash}")
            except (AttributeError, sqlite3.Error) as e:
                log(f"Error storing request in cache DB: {e}", level="WARNING")

    def get_request(self, rhash: str, expire: int = None) -> dict:
        """Get request data by hash."""
        with self._lock:
            try:
                self._cursor.execute(
                    "SELECT data,added FROM request WHERE hash = ?;",
                    (rhash,)
                )
                data = self._cursor.fetchone()
            except (AttributeError, sqlite3.Error) as e:
                log(f"Error fetching request from cache DB: {e}", level="WARNING")
                return None
            if not data:
                log(f"Request not found in cache DB: {rhash}")
                return None
            if not expire:
                expire = self._default_expire
            if data[1] + expire < dt.now().timestamp():
                log(f"Request expired in cache DB: {rhash}")
                return None
            log(f"Request found in cache DB: {rhash}")
            return json.loads(base64.b64decode(data[0]).decode("utf-8"))

    def run(self):
        """Run the database cleanup."""
        log(f"Start database cleanup for db '{os.path.basename(self._file)}'")
        self._table_cleanup("media")
        self._table_cleanup("request")
        log(f"End database cleanup for db '{os.path.basename(self._file)}'")

    def close(self):
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            log(f"Database connection closed for '{os.path.basename(self._file)}'")

    def _table_cleanup(self, table: str):
        """Cleanup old entries from the specified table."""
        with self._lock:
            try:
                self._cursor.execute(
                    f"DELETE FROM {table} WHERE added < ?;",
                    (dt.now().timestamp() - self._default_expire,)
                )
                self._conn.commit()
                log(f"Cleaned up table '{table}'")
            except (AttributeError, sqlite3.Error) as e:
                log(f"Error cleaning up table '{table}': {e}", level="WARNING")
