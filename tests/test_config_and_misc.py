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
    search_preference_score,
    sort_data,
)


def test_config_persists_nested_values_and_honors_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("cineflow.core.config.config_directory", lambda: tmp_path)
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
    monkeypatch.setattr("cineflow.core.config.config_directory", lambda: tmp_path)
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


def test_search_preference_score_is_a_strict_priority() -> None:
    preferences = ["HUN", "HDR", "1080p", "2160p"]
    score = lambda name: search_preference_score(name, preferences)  # noqa: E731

    # the first word decides: one HUN release beats any release without it
    assert score("Movie.2024.720p.HUN") > score("Movie.2024.2160p.HDR.1080p.ENG")
    # the next word only decides on a tie
    assert score("Movie.2024.1080p.HUN.HDR") > score("Movie.2024.1080p.HUN") > score("Movie.2024.2160p.HUN")
    assert score("Movie.2024.1080p.HUN") == 1 + 16 + 4
    assert score("Movie.2024.WEB") == search_preference_score("Movie.2024.WEB") == 1
    assert search_preference_score(None, preferences) == 0


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
        ("Some.Movie.2005.1080.Hun.DVDRip", "hun", "token", False, True),
        ("Hungry.Movie.2000", "hun", "token", False, False),
        ("Some_Movie-HUN", "hun", "token", False, True),
        ("Some.Movie.HUN", "hun", "token", True, False),
        ("12.5", "20", "lt", True, True), ("5", "5.0", "eq", True, True), ("5", "6", "ne", True, True),
        ("5", "5", "ne", True, False),
    ],
)
def test_evaluate_operators(left, right, expression, case, expected) -> None:
    assert evaluate(left, right, expression, case) is expected


def test_has_word_separates_words_at_any_non_alphanumeric_character() -> None:
    from cineflow.utils.misc import has_word

    for text in ("Movie.HUN.x264", "Movie-HUN-GRP", "Movie_HUN", "Movie [HUN]", "HUN", "Movie(HUN)"):
        assert has_word(text, "HUN"), text
    assert not has_word("Hungry.Movie", "HUN")
    assert not has_word("Movie.hun", "HUN") and has_word("Movie.hun", "HUN", case_sensitive=False)
    assert not has_word(None, "HUN") and not has_word("Movie", "") and has_word(2160, 2160)


def test_broken_config_at_startup_raises_a_clear_error(isolated_config_directory) -> None:
    config = Config()
    (isolated_config_directory / "config.yaml").write_text("a: [1,\n", encoding="utf-8")

    with pytest.raises(ValueError, match="cannot be loaded"):
        config.get("a")


def test_broken_config_while_running_keeps_last_valid_state(isolated_config_directory) -> None:
    config = Config()
    config_file = isolated_config_directory / "config.yaml"
    config_file.write_text("tmdb:\n  token: valid\n", encoding="utf-8")
    assert config.get("tmdb.token") == "valid"

    config_file.write_text("tmdb: [broken\n", encoding="utf-8")

    assert config.get("tmdb.token") == "valid"


def test_non_mapping_config_keeps_last_valid_state(isolated_config_directory) -> None:
    config = Config()
    config_file = isolated_config_directory / "config.yaml"
    config_file.write_text("execution: sequential\n", encoding="utf-8")
    assert config.get("execution") == "sequential"

    config_file.write_text("- just\n- a list\n", encoding="utf-8")

    assert config.get("execution") == "sequential"


def test_missing_config_file_is_an_empty_configuration(isolated_config_directory) -> None:
    config = Config()
    (isolated_config_directory / "config.yaml").unlink()

    assert config.get("execution", default="parallel") == "parallel"
