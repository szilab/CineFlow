"""Configuration and pure utility behavior tests."""

import subprocess
import sys

import pytest

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


def test_config_persists_nested_values_and_honors_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CFG_DIRECTORY", str(tmp_path))
    config = Config()
    config.set("tmdb.token", "secret")

    assert config.get("tmdb.token") == "secret"
    assert config.get("missing", default="fallback") == "fallback"
    assert cfg("tmdb.language", value="en") == "en"
    assert config.get("tmdb") == {"token": "secret", "language": "en"}


def test_config_uses_suite_isolated_directory(isolated_config_directory) -> None:
    """The default test configuration never depends on the runtime /config path."""
    config = Config()

    assert config._file == str(isolated_config_directory / "config.yaml")
    assert isolated_config_directory.is_dir()


def test_config_required_and_environment_module_override(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CFG_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("TMDB_TOKEN", "environment-token")

    assert Config.getfrom({"token": "file-token"}, "token", module="tmdb") == "environment-token"
    with pytest.raises(ValueError, match="required"):
        cfg("absent", required=True)


@pytest.mark.parametrize(
    ("environment", "configured", "default", "expected"),
    [
        ("true", False, None, True),
        ("OFF", True, None, False),
        ("50", 10, None, 50),
        ("1.25", 0.5, None, 1.25),
        ("ordinary", "configured", None, "ordinary"),
        ("012345", None, None, "012345"),
        ("42", None, 1, 42),
    ],
)
def test_environment_override_preserves_known_types(
    monkeypatch, environment, configured, default, expected
) -> None:
    monkeypatch.setenv("TMDB_VALUE", environment)
    config = {} if configured is None else {"value": configured}

    assert Config.getfrom(config, "value", module="tmdb", default=default) == expected


@pytest.mark.parametrize(
    ("environment", "hint"),
    [("maybe", False), ("twelve", 1), ("many", 1.0)],
)
def test_malformed_typed_environment_override_raises(monkeypatch, environment, hint) -> None:
    monkeypatch.setenv("TMDB_VALUE", environment)

    with pytest.raises(ValueError, match="TMDB_VALUE"):
        Config.getfrom({"value": hint}, "value", module="tmdb")


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


def test_module_lookup_uses_registries_without_scanning_files(monkeypatch) -> None:
    monkeypatch.setattr("pathlib.Path.iterdir", lambda _path: pytest.fail("filesystem scan"))

    assert load_module("tmdb").__name__ == "Tmdb"
    assert load_module("library").__name__ == "Library"


def test_parallel_module_loading_does_not_deadlock() -> None:
    """Sibling modules can be imported concurrently in a fresh interpreter."""
    code = """
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from cineflow.utils.misc import load_module

barrier = Barrier(2)

def load(name):
    barrier.wait()
    return load_module(name).__name__

with ThreadPoolExecutor(max_workers=2) as executor:
    results = list(executor.map(load, ("jackett", "jellyfin")))

assert results == ["Jackett", "Jellyfin"], results
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


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
