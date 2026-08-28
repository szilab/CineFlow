"""Plex failure propagation regression tests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cineflow.integrations.plex import Plex


def response(status: int, data=None):
    """Create a minimal mocked request response."""
    return SimpleNamespace(status=status, data=data)


def plex() -> Plex:
    """Create Plex without its network-backed initializer."""
    client = Plex.__new__(Plex)
    client._handler = Mock()
    client._library_list = {"first": "1", "second": "2"}
    client._kind = "movie"
    client.map = Mock(side_effect=lambda item: item)
    return client


def test_search_empty_success_returns_empty_list() -> None:
    client = plex()
    client._handler.get.return_value = response(200, {"MediaContainer": {"Metadata": []}})

    assert client._get_items({"searchTerm": "missing"}) == []


@pytest.mark.parametrize("status", [0, 404, 500])
def test_search_failures_return_none(status: int) -> None:
    client = plex()
    client._handler.get.return_value = response(status)

    assert client._get_items({"searchTerm": "missing"}) is None


@pytest.mark.parametrize("status", [0, 404])
def test_section_failures_return_none(status: int) -> None:
    client = plex()
    client._handler.get.return_value = response(status)

    assert client._get_items({"sectionKey": "1"}) is None


def test_full_library_discards_partial_results_when_a_section_fails() -> None:
    client = plex()
    client._handler.get.side_effect = [
        response(200, {"MediaContainer": {"Metadata": [{"title": "first"}]}}),
        response(500),
    ]

    assert client._get_items({}) is None


def test_inverse_full_library_failure_returns_none() -> None:
    client = plex()
    client._get_items = Mock(return_value=None)

    assert client._inverse_items([{"plexid": "included"}]) is None


def test_inverse_empty_full_library_returns_empty_list() -> None:
    client = plex()
    client._get_items = Mock(return_value=[])

    assert client._inverse_items([{"plexid": "included"}]) == []


def test_inverse_empty_query_input_returns_empty_list() -> None:
    assert plex()._inverse_items([]) == []


@pytest.mark.parametrize("status", [0, 500])
def test_library_initialization_failures_are_distinct_from_empty_libraries(status: int) -> None:
    client = plex()
    client._handler.get.return_value = response(status)

    with pytest.raises(ValueError, match=f"Failed to query Plex libraries: HTTP {status}"):
        client._get_libraries()


def test_empty_library_initialization_keeps_no_libraries_error() -> None:
    client = plex()
    client._handler.get.return_value = response(200, {"MediaContainer": {"Directory": []}})

    with pytest.raises(ValueError, match="No libraries found in Plex"):
        client._get_libraries()
