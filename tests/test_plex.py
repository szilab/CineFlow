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


def test_construction_does_not_contact_plex(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(Plex, "_get_libraries", lambda self: calls.append("libraries") or {"Movies": "1"})
    client = Plex(config={"url": "http://plex", "token": "token"})
    assert calls == []
    client._handler = Mock()
    client._handler.get.return_value = response(200, {"MediaContainer": {"Metadata": []}})

    assert client.get({"parentLibrary": "Movies"}) == []
    assert client.get() == []
    assert calls == ["libraries"]


@pytest.mark.parametrize("query", [{"searchTerm": "Film"}, {"sectionKey": "1"}, {}])
def test_item_requests_ask_plex_for_provider_guids(query: dict) -> None:
    client = plex()
    client._handler.get.return_value = response(200, {"MediaContainer": {"Metadata": []}})

    client._get_items(query)

    assert all(call.kwargs["params"]["includeGuids"] == "1" for call in client._handler.get.call_args_list)


def test_list_input_is_treated_as_items_not_as_a_query() -> None:
    """A list from a previous step selects inverse input instead of crashing query parsing."""
    client = plex()
    client._handler.get.return_value = response(200, {"MediaContainer": {"Metadata": []}})

    assert client._parse_query([{"plexid": "1"}]) == {}
    assert client.get([{"plexid": "1"}]) == []


def test_unknown_parent_library_is_rejected() -> None:
    with pytest.raises(ValueError, match="not found in Plex"):
        plex()._parse_query({"parentLibrary": "missing"})
