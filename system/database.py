"""Database module for storing media information"""

import os
import threading
import sqlite3
from typing import Any
from system.logger import log
from system.config import Config
from bases.enums import MediaType


class Database:
    """Database class for storing media information"""
    _instances = {}
    _path = os.path.join(Config().get_data_dir(), 'database.db')
    _lock = threading.Lock()

    def __call__(self, *args, **kwargs):
        if self not in self._instances:
            self._instances[self] = super(Database, self).__call__(*args, **kwargs)  # pylint: disable=no-member
        return self._instances[self]

    def __init__(self):
        self.conn = sqlite3.connect(self._path)
        self.cursor = self.conn.cursor()
        self._fields = {}
        if os.path.getsize(self._path) == 0:
            for media_type in MediaType:
                self.create_tables(table=media_type.value)
                self._fields.update({
                    media_type.value: ['title', 'aliases', 'year', 'created_at', 'updated_at']
                })
        else:
            for media_type in MediaType:
                self.cursor.execute(f"PRAGMA table_info({media_type.value})")
                self._fields.update({media_type.value: [row[1] for row in self.cursor.fetchall()]})

    def create_tables(self, table: str):
        """Create tables in database"""
        with self._lock:
            self.cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {table} (
                    title TEXT,
                    aliases TEXT,
                    year TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.commit()

    def add(self, table: str, title: str, year: str, alias: str = None, **kwargs):
        """Add item to database"""
        if item := self.get(table=table, title=title, alias=alias, year=year):
            log(f"Item already exists '{title} ({year})' in database", level='DEBUG')
        else:
            log(f"Inserting '{title} ({year})' into database")
            self.cursor.execute(f"""
                INSERT INTO {table} (title, aliases, year, created_at, updated_at)
                VALUES (
                    '{title}',
                    '{alias + ', ' if alias else ''}',
                    '{year}',
                    CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP
                )
            """)
            self.conn.commit()
            item = self.get(table=table, title=title, alias=alias, year=year)
        if kwargs:
            self._update(table=table, item=item, alias=alias, **kwargs)

    def _update(self, table: str, item: dict, alias: str = None, **kwargs):
        if alias and alias not in item['aliases']:
            self._update_fields(
                table=table,
                item=item,
                name='aliases',
                value=f"{alias}, {item['aliases']}"
            )
        self._extend_table_fields(table=table, fields=kwargs.keys())
        for key, value in kwargs.items():
            if not item.get(key): # or str(item[key]) != str(value):
                self._update_fields(table=table, item=item, name=key, value=value)
            else:
                log(
                    f"Field '{key}' already set for '{item['title']} "
                    f"({item['year']})' in {table}", level='DEBUG'
                )

    def get(self, table: str, title: str, alias: str, year: str) -> Any:
        """Get item from database"""
        with self._lock:
            self.cursor.execute(
                f"SELECT * FROM {table} "
                f"WHERE (title='{title}' OR aliases LIKE '%{title},%') AND year='{year}'"
            )
            item = self.cursor.fetchone()
            if item:
                return {f"{field}": item[i]  for i, field in enumerate(self._fields[table])}
            if not alias or alias == '':
                return None
            self.cursor.execute(
                f"SELECT * FROM {table} "
                f"WHERE (title='{alias}' OR aliases LIKE '%{alias},%') AND year='{year}'"
            )
            item = self.cursor.fetchone()
            if item:
                return {f"{field}": item[i]  for i, field in enumerate(self._fields[table])}
            return None

    def get_all(self, table: str) -> list:
        """Get all items from database"""
        with self._lock:
            self.cursor.execute(f"SELECT * FROM {table}")
            items = self.cursor.fetchall()
            data = []
            for item in items:
                data.append({f"{field}": item[i]  for i, field in enumerate(self._fields[table])})
            return data

    def _update_fields(self, table: str, item: dict, name: str, value: str):
        with self._lock:
            log(f"Updating {name} for {item['title']} in {table}", level='DEBUG')
            self.cursor.execute(f"""
                UPDATE {table}
                SET {name}="{str(value).replace('"', '')}", updated_at=CURRENT_TIMESTAMP
                WHERE title='{item['title']}' AND year='{item['year']}'
            """)
            self.conn.commit()

    def _extend_table_fields(self, table: str, fields: list):
        for f in fields:
            if f not in self._fields[table]:
                with self._lock:
                    self.cursor.execute(f"ALTER TABLE {table} ADD COLUMN {f} TEXT")
                    self.conn.commit()
                    self._fields[table].append(f)
