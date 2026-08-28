"""Tests for internal workflow modules without external services."""

from pathlib import Path

from cineflow.internal.library import Library
from cineflow.internal.tools import Tools


class FakeHandler:
    """Small in-memory directory adapter for Library behavior."""

    def __init__(self) -> None:
        self.items = {}
        self.created = []
        self.removed = []

    def all(self):
        return [Path(name) for name in self.items]

    def imprt(self, item):
        return self.items.get(item)

    def exists(self, item):
        return item in self.items

    def make(self, item, image, resolution):
        self.created.append((item, image, resolution))
        self.items.setdefault(item, {})
        return True

    def export(self, item, media):
        self.items[item] = dict(media)

    def remove(self, item):
        self.removed.append(item)
        self.items.pop(item, None)


def library(handler: FakeHandler) -> Library:
    """Create a library with its orchestration dependencies replaced by a fake."""
    instance = Library.__new__(Library)
    instance._handler = handler
    instance._cfg = {}
    instance._data_mappings = {"title": ["title"], "year": ["year"]}
    instance._empty_property_allowed = False
    instance.mappings = {
        "directory": ["directory"], "title": ["title"], "year": ["year"],
        "tmdbid": ["tmdbid"], "imdbid": ["imdbid"],
    }
    instance.transforms = {"tmdbid": lambda value: int(value) if value else None, "imdbid": lambda value: value}
    return instance


def test_library_get_maps_valid_entries_and_retains_unknown_directories() -> None:
    handler = FakeHandler()
    handler.items = {"Known (2024)": {"title": "Known", "year": 2024}, "odd-name": {}}
    result = library(handler).get()
    assert result == [{"title": "Known", "year": 2024}]


def test_library_put_skips_identical_media_and_exports_poster(monkeypatch) -> None:
    handler = FakeHandler()
    item = "Film (2024) [tmdbid-7]"
    handler.items[item] = {"title": "Film", "year": 2024, "tmdbid": 7, "resolution": "1080p"}
    instance = library(handler)
    monkeypatch.setattr(instance, "_create_poster", lambda media: "poster-image")
    media = {"title": "Film", "year": 2024, "tmdbid": 7, "poster": "url", "resolution": "1080p"}

    assert instance.put([dict(media)]) == [media]
    assert handler.created == []
    changed = dict(media, tmdbid=8)
    instance.put([changed])
    assert handler.created == [("Film (2024) [tmdbid-8]", "poster-image", "1080p")]
    assert changed["directory"] == "Film (2024) [tmdbid-8]"


def test_library_remove_and_poster_rules(monkeypatch) -> None:
    handler = FakeHandler()
    handler.items = {"Film (2024)": {}, "Alt (2024)": {}}
    instance = library(handler)
    instance.remove([{"title": "Film", "alttitle": "Alt", "year": 2024}])
    assert handler.removed == ["Film (2024)", "Alt (2024)"]

    class Poster:
        def __init__(self): self.rules = []
        def apply_from_rule(self, rule): self.rules.append(rule)
    poster = Poster()
    monkeypatch.setattr("cineflow.internal.library.ImageHandler", lambda url: poster)
    instance.cfg = lambda key: [{"property": "status", "value": "new", "expression": "eq"}] if key == "rules" else None
    assert instance._create_poster({"title": "Film", "poster": "url", "status": "new"}) is poster
    assert len(poster.rules) == 1


def test_tools_exports_imports_and_removes_duplicate_identity(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("DEBUG_DIRECTORY", str(tmp_path))
    tools = Tools()
    data = [
        {"title": "One", "year": 2024, "imdbid": 1},
        {"title": "Duplicate", "year": 2024, "imdbid": 1},
        {"title": "Two", "year": 2023, "tmdbid": 2},
    ]
    tools.data_export(data, "data.json")
    assert tools.data_import("data.json") == data
    assert tools.data_import("missing.json") == []
    assert tools.remove_duplicates(data) == [data[0], data[2]]
