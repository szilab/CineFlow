"""Database module for storing media information"""

import os
import threading
import sqlite3
import json
import base64

from system.logger import log
from bases.singleton import SingletonMeta


class Database(metaclass=SingletonMeta):
    # TO-DO: Add matedate refresh based on added time
    """Database class for storing media information"""

    def __init__(self):
        self._file = os.environ.get("DATA_DIRECTORY" ,"/data") + "/db.sqlite3"
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(self._file)
        self.cursor = self.conn.cursor()
        self.create_tables()

    def create_tables(self):
        """Create tables in database"""
        if os.path.getsize(self._file) == 0:
            log("Creating cache DB tables.", level="DEBUG")
            with self._lock:
                self.cursor.execute("""
                    CREATE TABLE IF NOT EXISTS cache (
                        source TEXT NOT NULL,
                        title TEXT NOT NULL,
                        year INTEGER NOT NULL,
                        kind TEXT NOT NULL,
                        data BLOB NOT NULL,
                        added REAL DEFAULT (julianday('now'))
                    );
                """.strip())
                self.conn.commit()

    def store_media(self, source: str, data: dict) -> None:
        """Add movie to the database"""
        if not data or not data.get('title') or not data.get('year') or not data.get('kind'):
            log(f"Invalid data for media cannot store in cache: {data}", level="DEBUG")
            return
        with self._lock:
            bytes_data = base64.b64encode(bytes(json.dumps(data), "utf-8"))
            self.cursor.execute(
                "INSERT INTO media (source, title, year, kind, data) VALUES (?, ?, ?, ?, ?);",
                (source, data.get('title'), data.get('year'), data.get('kind'), bytes_data,)
            )
            self.conn.commit()
            log(f"Added media to cache DB: {data.title} ({data.year})", level="DEBUG")

    def get_media(self, source: str, title: str, year: int, kind: str) -> dict:
        """Get movie by title"""
        with self._lock:
            self.cursor.execute(
                "SELECT data FROM media WHERE source = ? AND title = ? AND year = ? AND kind = ?;",
                (source, title, year, kind,)
            )
            data = self.cursor.fetchone()
            if not data[0]:
                log(f"Media not found in cache DB: {title} ({year})", level="DEBUG")
                return None
            return json.loads(base64.b64decode(data[0]).decode("utf-8"))
