"""Tests for internal workflow modules without external services."""

import json
from pathlib import Path

from cineflow.core import catalog
from cineflow.internal.library import Library
from cineflow.internal.tools import Tools
from cineflow.utils.directory import CleanupScheduler


class FakeHandler:
    """Small in-memory directory adapter for Library behavior."""

    def __init__(self) -> None:
        self.items = {}
        self.created = []
        self.removed = []
        self.cleanups = 0

    def cleanup(self):
        self.cleanups += 1

    def all(self):
        return [Path(name) for name in self.items]

    def imprt(self, item):
        return self.items.get(item)

    def exists(self, item):
        return item in self.items

    def publish(self, item, media, image, resolution, kind="movie"):
        self.kinds = [*getattr(self, "kinds", []), kind]
        self.created.append((item, image, resolution))
        self.items[item] = dict(media)
        return True

    def remove(self, item):
        self.removed.append(item)
        self.items.pop(item, None)


def library(handler: FakeHandler) -> Library:
    """Create a library with its orchestration dependencies replaced by a fake."""
    instance = Library.__new__(Library)
    instance.name = "library"
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
    # cleanup runs in the background worker, never as part of a read
    assert handler.cleanups == 0


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


def test_library_put_only_replaces_a_release_with_a_better_preference_score(monkeypatch) -> None:
    handler = FakeHandler()
    item = "Film (2024) [tmdbid-7]"
    existing = {
        "title": "Film", "year": 2024, "tmdbid": 7, "poster": "old-poster",
        "torrent": "Film.2024.1080p.HUN.WEB", "seeders": 20, "link": "old-link",
    }
    handler.items[item] = dict(existing)
    instance = library(handler)
    monkeypatch.setattr(instance, "_create_poster", lambda media: "poster-image")
    instance._cfg = {"search_preference": ["HUN", "HDR", "1080p", "2160p"]}

    same_release = dict(existing, seeders=200, link="new-link")
    instance.put([same_release])

    assert handler.created == []
    assert handler.items[item] == existing

    better_release = dict(
        same_release,
        torrent="Film.2024.1080p.HUN.HDR.WEB",
        poster="new-poster",
    )
    instance.put([better_release])

    assert handler.created == [(item, "poster-image", None)]
    assert handler.items[item]["torrent"] == better_release["torrent"]


def test_library_ranking_ignores_jackett_configuration(
    tmp_path, monkeypatch, isolated_config_directory,
) -> None:
    """Library release ranking only uses the library's own configuration."""
    monkeypatch.setenv("EXPORT_DIRECTORY", str(tmp_path / "export"))
    isolated_config_directory.mkdir(parents=True, exist_ok=True)
    (isolated_config_directory / "config.yaml").write_text(
        "jackett:\n  search_preference: [HUN]\nlibrary:\n  directory: movies\n", encoding="utf-8",
    )
    instance = Library()
    assert instance.cfg("search_preference", default=[]) == []
    handler = FakeHandler()
    item = "Film (2024) [tmdbid-7]"
    handler.items[item] = {"title": "Film", "year": 2024, "tmdbid": 7, "torrent": "Film.2024.1080p"}
    instance._handler = handler
    monkeypatch.setattr(instance, "_create_poster", lambda media: "poster-image")
    candidate = {"title": "Film", "year": 2024, "tmdbid": 7, "poster": "url", "torrent": "Film.2024.1080p.HUN"}

    instance.put([candidate])

    assert handler.created == []


def test_library_construction_schedules_background_cleanup(
    tmp_path, monkeypatch, isolated_config_directory,
) -> None:
    monkeypatch.setenv("EXPORT_DIRECTORY", str(tmp_path / "export"))
    first = Library(config={"directory": "movies"})
    second = Library(config={"directory": "movies", "limit": 20})

    worker = CleanupScheduler._workers[first._handler.path]
    assert worker.handler is second._handler
    assert worker.handler.max_item_count == 20
    assert worker.delay == 60


def test_library_put_reuses_a_matching_tmdb_directory_when_title_or_year_changes(monkeypatch) -> None:
    handler = FakeHandler()
    existing_item = "You+Me - Against the World (2026) [tmdbid-1641629]"
    existing = {
        "title": "You+Me - Against the World", "year": 2026, "tmdbid": 1641629,
        "torrent": "You.Me.2026.1080p.HUN.WEB", "poster": "old-poster",
    }
    handler.items[existing_item] = dict(existing)
    instance = library(handler)
    monkeypatch.setattr(instance, "_create_poster", lambda media: "poster-image")
    instance._cfg = {"search_preference": ["HUN", "HDR", "1080p"]}
    candidate = {
        **existing,
        "title": "You+Me – Against the World",
        "year": 2025,
        "torrent": "You.Me.2026.1080p.HUN.HDR.WEB",
        "poster": "new-poster",
    }

    instance.put([candidate])

    assert list(handler.items) == [existing_item]
    assert handler.created == [(existing_item, "poster-image", None)]
    assert handler.items[existing_item]["directory"] == existing_item


def test_library_put_then_get_keeps_new_item_visible_to_downstream(monkeypatch) -> None:
    handler = FakeHandler()
    instance = library(handler)
    monkeypatch.setattr(instance, "_create_poster", lambda media: "poster-image")
    media = {"title": "New", "year": 2026, "poster": "url"}

    instance.put([media])
    result = instance.get()

    assert result == [{"directory": "New (2026)", "title": "New", "year": 2026}]
    assert handler.cleanups == 0


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
    rules = [
        {"property": "torrent", "value": "HUN", "expression": "token", "modification": "border"},
        {"property": "seeders", "value": 40, "expression": "gt", "modification": "triangle"},
        {"property": "size", "value": "20", "expression": "lt", "modification": "grayscale"},
        {"property": "imdbid", "expression": "missing", "modification": "grayscale"},
        "not a rule",
    ]
    instance.cfg = lambda key: rules if key == "poster_rules" else None
    media = {"title": "Film", "poster": "url", "torrent": "Film.2024.HUN.1080p", "seeders": 120, "size": 12.5,
             "imdbid": 42}
    assert instance._create_poster(media) is poster
    # numbers such as seeders and size compare as numbers, not text
    assert [rule["modification"] for rule in poster.rules] == ["border", "triangle", "grayscale"]

    # text rules ignore case by default, and `case_sensitive: true` restores exact matching
    poster.rules.clear()
    rules[:] = [{"property": "torrent", "value": "hun", "expression": "token", "modification": "border"},
                {"property": "torrent", "value": "hun", "expression": "token", "modification": "triangle",
                 "case_sensitive": True}]
    instance._create_poster(media)
    assert [rule["modification"] for rule in poster.rules] == ["border"]


def test_poster_rules_are_a_setting_of_the_export_step() -> None:
    from cineflow.core.validation import validate_flow

    definition = catalog.definitions()["library"]
    assert "rules" not in {spec.key for spec in definition.fields}
    put = definition.action("put").to_dict()
    assert [spec["key"] for spec in put["fields"]] == ["poster_rules"]
    assert [spec["key"] for spec in put["fields"][0]["item_fields"]] == [
        "property", "expression", "value", "case_sensitive", "modification", "color", "position"]

    def errors(rules) -> list:
        flow = {"name": "x", "steps": [
            {"name": "Load", "module": "tools", "action": "data_import"},
            {"name": "Export", "module": "library", "action": "put", "input": "previous",
             "config": {"poster_rules": rules}},
        ]}
        return [(".".join(map(str, issue.path)), issue.code)
                for issue in validate_flow(flow, {"library": {}}) if issue.level == "error"]

    assert errors([{"property": "torrent", "expression": "token", "value": "HUN",
                    "modification": "border", "color": "green", "position": "top-left"}]) == []
    assert errors([{"property": "torrent", "modification": "sepia", "color": "pink"}]) == [
        ("steps.1.config.poster_rules.0.modification", "choice"),
        ("steps.1.config.poster_rules.0.color", "choice"),
    ]


def test_tools_exports_imports_and_removes_duplicate_identity(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("cineflow.internal.tools.debug_directory", lambda: tmp_path)
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


def test_tools_export_creates_nested_directory_and_removes_adjacent_duplicates(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("cineflow.internal.tools.debug_directory", lambda: tmp_path / "debug")
    tools = Tools()
    data = [
        {"title": "First", "year": 2024, "imdbid": 1},
        {"title": "Duplicate", "year": 2024, "imdbid": 1},
        {"title": "Duplicate again", "year": 2024, "imdbid": 1},
    ]

    tools.data_export(data, "nested/data.json")

    assert tools.data_import("nested/data.json") == data
    assert tools.remove_duplicates(data) == [data[0]]


def test_library_export_directory_setting_and_its_environment_override(
    tmp_path, monkeypatch, isolated_config_directory,
) -> None:
    isolated_config_directory.mkdir(parents=True, exist_ok=True)
    (isolated_config_directory / "config.yaml").write_text(
        f"library:\n  export_directory: {tmp_path / 'share'}\n", encoding="utf-8",
    )

    assert Library(config={"directory": "movie"})._handler.path == tmp_path / "share" / "movie"
    monkeypatch.setenv("EXPORT_DIRECTORY", str(tmp_path / "env"))
    assert Library(config={"directory": "movie"})._handler.path == tmp_path / "env" / "movie"


def test_library_defaults_to_the_application_root(tmp_path) -> None:
    assert Library(config={"directory": "tv"})._handler.path == tmp_path / "home" / "cineflow" / "library" / "tv"


ITEMS = [
    {"title": "Dune", "year": "2024", "torrent": "Dune.2024.2160p.HUN.x265", "seeders": 40, "size": 12.5},
    {"title": "Alien", "year": 1979, "torrent": "Alien.1979.1080p.x264", "seeders": 5},
    {"title": "Untitled"},
]


def titles(items) -> list:
    return [item["title"] for item in items]


def cond(field: str, value, match: str | None = None) -> dict:
    return {"field": field, "value": value, **({"match": match} if match else {})}


def where(*conditions, **options) -> dict:
    return {"conditions": list(conditions), **options}


def test_tools_filter_keeps_items_whose_field_contains_the_value() -> None:
    hungarian = cond("torrent", "hun", "contains")

    assert titles(Tools().filter_items(ITEMS, where(hungarian))) == ["Dune"]
    assert titles(Tools().filter_items(ITEMS, where(hungarian, matching="drop"))) == ["Alien", "Untitled"]
    assert titles(Tools().filter_items(ITEMS, where(hungarian, matching="keep"))) == ["Dune"]


def test_tools_filter_at_least_and_at_most_compare_numbers() -> None:
    tools = Tools()

    assert titles(tools.filter_items(ITEMS, where(cond("seeders", "10", "at_least")))) == ["Dune"]
    assert titles(tools.filter_items(ITEMS, where(cond("seeders", "10", "at_most")))) == ["Alien"]
    assert titles(tools.filter_items(ITEMS, where(cond("seeders", 40, "at_most")))) == ["Dune", "Alien"]
    assert titles(tools.filter_items(ITEMS, where(cond("year", "2000", "at_least")))) == ["Dune"]
    assert titles(tools.filter_items(ITEMS, where(cond("title", "5", "at_least")))) == []
    assert titles(tools.filter_items(ITEMS, where(cond("seeders", "10", "at_least"), matching="drop"))) == [
        "Alien", "Untitled"]
    assert tools.filter_items(ITEMS, where(cond("seeders", "10", "between"))) == ITEMS


def test_tools_filter_equals_compares_numbers_by_value_and_text_without_case() -> None:
    tools = Tools()

    assert titles(tools.filter_items(ITEMS, where(cond("year", "1979")))) == ["Alien"]
    assert titles(tools.filter_items(ITEMS, where(cond("size", "12.50", "equals")))) == ["Dune"]
    assert titles(tools.filter_items(ITEMS, where(cond("title", "DUNE")))) == ["Dune"]
    assert titles(tools.filter_items(ITEMS, where(cond("title", "Dun")))) == []
    assert titles(tools.filter_items([{"title": "A", "kind": ["tv", "movie"]}],
                                     where(cond("kind", "tv", "contains")))) == ["A"]


def test_tools_filter_has_word_matches_whole_words_without_case() -> None:
    releases = [
        {"title": "A", "torrent": "Film.2024.1080p.HUN-GRP"},
        {"title": "B", "torrent": "Film_2024 [hun] x264"},
        {"title": "C", "torrent": "Hungry.Film.2024.1080p"},
        {"title": "D", "torrent": "Film.2024.HUNSUB"},
    ]

    assert titles(Tools().filter_items(releases, where(cond("torrent", "HUN", "has_word")))) == ["A", "B"]
    assert titles(Tools().filter_items(releases, where(cond("torrent", "hun", "contains")))) == ["A", "B", "C", "D"]


def test_tools_filter_combines_conditions_with_and_or_or() -> None:
    releases = [
        {"title": "A", "torrent": "A.2160p.HDR.x265", "seeders": 50},
        {"title": "B", "torrent": "B.2160p.DV.Dolby.Vision", "seeders": 45},
        {"title": "C", "torrent": "C.1080p.HDR.x264", "seeders": 3},
        {"title": "D", "torrent": "D.1080p.x264", "seeders": 90},
    ]
    hdr, dolby = cond("torrent", "HDR", "contains"), cond("torrent", "dolby", "contains")
    seeded = cond("seeders", 40, "at_least")
    tools = Tools()

    assert titles(tools.filter_items(releases, where(hdr, seeded))) == ["A"]
    assert titles(tools.filter_items(releases, where(hdr, seeded, combine="all"))) == ["A"]
    assert titles(tools.filter_items(releases, where(hdr, dolby, combine="any"))) == ["A", "B", "C"]
    assert titles(tools.filter_items(releases, where(hdr, dolby, combine="any", matching="drop"))) == ["D"]
    assert titles(tools.filter_items(releases, where(hdr, seeded, matching="drop"))) == ["B", "C", "D"]


def test_tools_filter_without_usable_conditions_keeps_every_item() -> None:
    tools = Tools()

    assert tools.filter_items(ITEMS, where({"field": "title"})) == ITEMS
    assert tools.filter_items(ITEMS, where(cond("title", "Dune"), {"value": "x"})) == ITEMS
    assert tools.filter_items(ITEMS, {"conditions": "title"}) == ITEMS
    assert tools.filter_items(ITEMS, where()) == ITEMS
    assert tools.filter_items(ITEMS, None) == ITEMS
    assert tools.filter_items(None, where(cond("title", "x"))) == []


def test_tools_filter_conditions_are_validated_item_by_item() -> None:
    from cineflow.core.validation import validate_flow

    def issues(conditions) -> list:
        flow = {"name": "Filter", "steps": [
            {"name": "Load", "module": "tools", "action": "data_import"},
            {"name": "F", "module": "tools", "action": "filter_items",
             "input": {"data": "previous", "query": {"conditions": conditions, "combine": "any"}}},
        ]}
        return [(".".join(map(str, issue.path)), issue.code) for issue in validate_flow(flow) if issue.level == "error"]

    assert issues([cond("torrent", "HDR", "contains"), cond("seeders", 40, "at_least")]) == []
    assert issues([{"field": "nope", "match": "between"}]) == [
        ("steps.1.input.query.conditions.0.field", "choice"),
        ("steps.1.input.query.conditions.0.match", "choice"),
        ("steps.1.input.query.conditions.0.value", "required"),
    ]
    assert issues(["torrent"]) == [("steps.1.input.query.conditions.0", "type")]


def test_tools_filter_runs_as_a_valid_flow_step_on_the_previous_items(tmp_path, monkeypatch) -> None:
    from cineflow.core import preview
    from cineflow.core.validation import validate_flow

    flow = {"name": "Filter", "enabled": False, "steps": [
        {"name": "Load", "module": "tools", "action": "data_import", "input": {"filename": "items.json"}},
        {"name": "Hungarian", "module": "tools", "action": "filter_items",
         "input": {"data": "previous",
                   "query": where(cond("torrent", "HUN", "contains"), cond("seeders", 10, "at_least"))}},
    ]}
    assert [issue for issue in validate_flow(flow) if issue.level == "error"] == []
    debug = tmp_path / "debug"
    debug.mkdir()
    (debug / "items.json").write_text(json.dumps(ITEMS))
    monkeypatch.setattr("cineflow.internal.tools.debug_directory", lambda: debug)

    result = preview.run_test(flow)

    assert result["status"] == "success"
    assert [(step["name"], step["count"]) for step in result["steps"]] == [("Load", 3), ("Hungarian", 1)]


def test_library_enrich_adds_stored_data_by_identity_then_title() -> None:
    """Items get the stored data of the matching library item; their own values win."""
    handler = FakeHandler()
    handler.items = {
        "Film (2024) [tmdbid-7]": {"title": "Film", "year": 2024, "tmdbid": 7, "torrent": "Film.2024.1080p",
                                   "resolution": "1080p"},
        "Other (2020)": {"title": "Other", "year": 2020, "imdbid": 99, "overview": "text"},
        "Broken (2021)": {},
        "odd-name": {"title": "Odd", "year": 2000},
    }
    instance = library(handler)
    data = [
        {"title": "Localized", "year": 2024, "tmdbid": 7, "resolution": "720p"},
        {"title": "Other", "year": "2020"},
        {"title": "Unknown", "alttitle": "other", "year": 2020},
        {"title": "Other", "year": 2019},
        {"title": "Odd", "year": 2000},
    ]

    result = instance.enrich(data)

    assert result == data
    assert data[0] == {"title": "Localized", "year": 2024, "tmdbid": 7, "resolution": "720p",
                       "torrent": "Film.2024.1080p", "directory": "Film (2024) [tmdbid-7]"}
    assert data[1]["overview"] == "text" and data[1]["directory"] == "Other (2020)"
    assert data[2]["directory"] == "Other (2020)"
    assert "directory" not in data[3] and "directory" not in data[4]
    assert instance.enrich(None) == []


def test_library_enrich_must_match_drops_and_series_match_without_year() -> None:
    """With must_match only found items go on; a series without a year matches by title."""
    handler = FakeHandler()
    handler.items = {"Show [tmdbid-3]": {"title": "Show", "tmdbid": 3, "season": 2}}
    instance = library(handler)
    instance.kind = "tv"
    instance._cfg = {"must_match": True}

    result = instance.enrich([{"title": "Show", "year": 2019}, {"title": "Missing"}])

    assert result == [{"title": "Show", "year": 2019, "tmdbid": 3, "season": 2, "directory": "Show [tmdbid-3]"}]


def test_library_enrich_is_offered_as_data_source() -> None:
    """The flow editor offers the library under "Add data from" of a source step."""
    action = catalog.definition("library").action("enrich")
    assert action.effective_stage == "enrich"
    assert [spec.key for spec in action.fields] == ["must_match"]
