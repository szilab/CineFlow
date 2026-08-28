"""Configuration and pure utility behavior tests."""

import pytest

from cineflow.core.bases.singleton import SingletonMeta
from cineflow.core.config import Config, cfg
from cineflow.utils.misc import (
    evaluate,
    fix_imdbid,
    load_module,
    media_resolution,
    media_title,
    media_year,
    sanitize_name,
    sanitize_path,
    sort_data,
)


@pytest.fixture(autouse=True)
def clear_config_singleton() -> None:
    """Keep each test's configuration file isolated."""
    SingletonMeta._instances.pop(Config, None)
    yield
    SingletonMeta._instances.pop(Config, None)


def test_config_persists_nested_values_and_honors_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CFG_DIRECTORY", str(tmp_path))
    config = Config()
    config.set("tmdb.token", "secret")

    assert config.get("tmdb.token") == "secret"
    assert config.get("missing", default="fallback") == "fallback"
    assert cfg("tmdb.language", value="en") == "en"
    assert config.get("tmdb") == {"token": "secret", "language": "en"}


def test_config_required_and_environment_module_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CFG_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("TMDB_TOKEN", "environment-token")

    assert Config.getfrom({"token": "file-token"}, "token", module="tmdb") == "environment-token"
    with pytest.raises(ValueError, match="required"):
        cfg("absent", required=True)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("Movie.Name-2024!", "MovieName 2024"), ("", ""), ("a/b:c", "abc")],
)
def test_sanitizers(value: str, expected: str) -> None:
    assert sanitize_name(value) == expected
    assert sanitize_path("a/b:c") == "abc"


def test_media_parsing_sorting_and_module_lookup() -> None:
    release = "A.Great.Movie.2024.2160p.WEB"
    assert media_title(release) == "A Great Movie"
    assert media_year(release) == "2024"
    assert media_resolution(release) == "2160p"
    assert media_resolution("unknown") == "N/A"
    assert sort_data([{"year": 2023}, {"year": 2024}], "year", reverse=True)[0]["year"] == 2024
    assert load_module("tools").__name__ == "Tools"
    assert load_module("not_a_module") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [({"Imdb": "tt123"}, 123), (" TT0042 ", 42), ("bad", None), (None, None)],
)
def test_fix_imdbid(value, expected) -> None:
    assert fix_imdbid(value) == expected


@pytest.mark.parametrize(
    ("left", "right", "expression", "case", "expected"),
    [
        ("10", "2", "gt", True, True), ("a", "A", "eq", False, True),
        ("CineFlow", "flow", "contains", False, True), (None, None, "missing", True, True),
        ("value", None, "none", True, True), ("x", "y", "ne", True, True),
    ],
)
def test_evaluate_operators(left, right, expression, case, expected) -> None:
    assert evaluate(left, right, expression, case) is expected
