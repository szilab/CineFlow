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


def media(title: str = "Arrival", year: int = 2016, kind: str = "movie", **extra: str) -> dict:
    """Build a minimal cacheable media value."""
    return {"title": title, "year": year, "kind": kind, **extra}


def test_creation_creates_all_required_tables(database: Database) -> None:
    tables = database._conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table';"
    ).fetchall()

    assert {"media", "request"}.issubset({name for name, in tables})


def test_media_upsert_keeps_one_row_and_returns_newest(database: Database) -> None:
    database.store_media("tmdb", media(version="first"))
    database.store_media("tmdb", media(version="second"))
    count = database._conn.execute("SELECT COUNT(*) FROM media;").fetchone()[0]

    assert count == 1
    assert database.get_media("tmdb", "Arrival", 2016, "movie")["version"] == "second"


def test_media_key_separates_sources_years_and_kinds(database: Database) -> None:
    database.store_media("tmdb", media(version="tmdb"))
    database.store_media("imdb", media(version="imdb"))
    database.store_media("tmdb", media(year=2017, version="new-year"))
    database.store_media("tmdb", media(kind="tv", version="tv"))

    assert database.get_media("imdb", "Arrival", 2016, "movie")["version"] == "imdb"
    assert database.get_media("tmdb", "Arrival", 2017, "movie")["version"] == "new-year"
    assert database.get_media("tmdb", "Arrival", 2016, "tv")["version"] == "tv"


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
        assert {"existing", "media", "request"}.issubset({name for name, in tables})
    finally:
        database.stop()
        database.close()
        SingletonMeta._instances.pop(Database, None)


def test_legacy_media_table_is_migrated_and_duplicates_keep_newest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "cachedb.sqlite3"
    connection = sqlite3.connect(db_file)
    connection.execute(
        "CREATE TABLE media (title TEXT NOT NULL, year INTEGER NOT NULL, kind TEXT "
        "NOT NULL, source TEXT NOT NULL, data BLOB NOT NULL, added REAL NOT NULL);"
    )
    now = dt.now().timestamp()
    for version, added in (("old", now - 1), ("new", now)):
        encoded = base64.b64encode(json.dumps(media(version=version)).encode("utf-8"))
        connection.execute(
            "INSERT INTO media VALUES (?, ?, ?, ?, ?, ?);",
            ("Arrival", 2016, "movie", "tmdb", encoded, added),
        )
    connection.commit()
    connection.close()
    monkeypatch.setenv("DB_DIRECTORY", str(tmp_path))

    SingletonMeta._instances.pop(Database, None)
    database = Database()
    try:
        assert database.get_media("tmdb", "Arrival", 2016, "movie")["version"] == "new"
        with pytest.raises(sqlite3.IntegrityError):
            database._conn.execute(
                "INSERT INTO media VALUES (?, ?, ?, ?, ?, ?);",
                ("Arrival", 2016, "movie", "tmdb", b"data", 3.0),
            )
    finally:
        database.stop()
        database.close()
        SingletonMeta._instances.pop(Database, None)
