"""Logger singleton and secret masking tests."""

import pytest

from cineflow.core import logger
from cineflow.core.logger import Logger, log, redact_secrets


@pytest.fixture
def fresh_logger(monkeypatch: pytest.MonkeyPatch):
    """Create the logger again so it reads the patched environment."""
    monkeypatch.setattr(Logger, "_instance", None)
    yield
    monkeypatch.setattr(Logger, "_instance", None)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            "Max retries exceeded with url: /api/v2.0/indexers/all/results?apikey=SECRET&Query=x",
            "Max retries exceeded with url: /api/v2.0/indexers/all/results?apikey=***&Query=x",
        ),
        ("/3/trending/movie/week?page=1&api_key=SECRET", "/3/trending/movie/week?page=1&api_key=***"),
        ("https://jackett/dl/x?jackett_apikey=SECRET&path=a", "https://jackett/dl/x?jackett_apikey=***&path=a"),
        ("params {'ApiKey': 'SECRET', 'Recursive': 'true'}", "params {'ApiKey': '***', 'Recursive': 'true'}"),
        ('{"X-Plex-Token": "SECRET"}', '{"X-Plex-Token": "***"}'),
        ("Arrival (2016) found", "Arrival (2016) found"),
    ],
)
def test_redact_secrets_masks_credentials(message: str, expected: str) -> None:
    assert redact_secrets(message) == expected


def test_log_output_never_contains_credentials(fresh_logger, capsys, monkeypatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")

    log("Request error 'https://api.test/x?api_key=SECRET'", level="WARNING")

    output = capsys.readouterr().out
    assert "SECRET" not in output
    assert "api_key=***" in output


def test_logger_is_configured_once_and_keeps_its_lock(fresh_logger) -> None:
    first = Logger()
    lock = first._lock

    assert Logger() is first
    assert Logger()._lock is lock


@pytest.mark.parametrize(("value", "expected"), [("false", False), ("0", False), ("", False), ("true", True)])
def test_log_colors_parse_boolean_strings(fresh_logger, monkeypatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("LOG_COLORS", value)

    assert Logger()._colors is expected


def test_lower_case_log_level_is_accepted(fresh_logger, monkeypatch, capsys) -> None:
    monkeypatch.setenv("LOG_LEVEL", "error")

    logger.log("hidden", level="WARNING")
    logger.log("shown", level="ERROR")

    output = capsys.readouterr().out
    assert "hidden" not in output
    assert "shown" in output
