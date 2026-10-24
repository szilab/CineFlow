"""Focused regression tests for the SQLite cache database."""

import base64
import json
import sqlite3
from datetime import datetime as dt
from pathlib import Path

import pytest

from cineflow.core.bases.singleton import SingletonMeta
from cineflow.core.database import Database


@pytest.fixture
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Database:
    """Provide an isolated database singleton backed by a temporary file."""
    monkeypatch.setenv("DB_DIRECTORY", str(tmp_path))
    SingletonMeta._instances.pop(Database, None)
    instance = Database()
    yield instance
    instance.stop()
    instance.close()
    SingletonMeta._instances.pop(Database, None)


def test_creation_creates_the_request_table(database: Database) -> None:
    tables = database._conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table';"
    ).fetchall()

    assert {name for name, in tables} == {"request"}


def test_request_cache_replaces_matching_hash(database: Database) -> None:
    database.store_request("request-hash", {"version": "first"})
    database.store_request("request-hash", {"version": "second"})

    assert database.get_request("request-hash") == {"version": "second"}


@pytest.mark.parametrize("data", [[], {}])
def test_request_cache_preserves_successful_empty_values(database: Database, data: object) -> None:
    database.store_request("empty-request", data)

    assert database.get_request("empty-request") == data


def test_existing_nonempty_database_gets_missing_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "cachedb.sqlite3"
    connection = sqlite3.connect(db_file)
    connection.execute("CREATE TABLE existing (value TEXT);")
    connection.commit()
    connection.close()
    monkeypatch.setenv("DB_DIRECTORY", str(tmp_path))

    SingletonMeta._instances.pop(Database, None)
    database = Database()
    try:
        tables = database._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table';"
        ).fetchall()
        assert {"existing", "request"}.issubset({name for name, in tables})
    finally:
        database.stop()
        database.close()
        SingletonMeta._instances.pop(Database, None)


def test_legacy_schema_gains_expiry_and_drops_unused_media_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "cachedb.sqlite3"
    connection = sqlite3.connect(db_file)
    connection.execute(
        "CREATE TABLE request (hash TEXT NOT NULL PRIMARY KEY, data BLOB NOT NULL, added REAL NOT NULL);"
    )
    connection.execute("CREATE TABLE media (title TEXT);")
    encoded = base64.b64encode(json.dumps({"version": "old"}).encode("utf-8"))
    connection.execute("INSERT INTO request VALUES (?, ?, ?);", ("kept", encoded, dt.now().timestamp()))
    connection.commit()
    connection.close()
    monkeypatch.setenv("DB_DIRECTORY", str(tmp_path))

    SingletonMeta._instances.pop(Database, None)
    database = Database()
    try:
        tables = database._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table';").fetchall()
        assert {name for name, in tables} == {"request"}
        assert database.get_request("kept") == {"version": "old"}
    finally:
        database.stop()
        database.close()
        SingletonMeta._instances.pop(Database, None)


def test_cleanup_keeps_entries_within_their_own_expiry(database: Database) -> None:
    now = dt.now().timestamp()
    database.store_request("long", {"value": 1}, expire=30 * 86400)
    database.store_request("default", {"value": 2})
    database._conn.execute("UPDATE request SET added = ?;", (now - 2 * 86400,))
    database._conn.commit()

    database.run()

    hashes = {row[0] for row in database._conn.execute("SELECT hash FROM request;")}
    assert hashes == {"long"}
