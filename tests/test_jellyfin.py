"""Regression tests for Jellyfin failure propagation."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cineflow.integrations.jellyfin import Jellyfin


def response(status: int, data=None):
    """Create a minimal mocked request response."""
    return SimpleNamespace(status=status, data=data)


def jellyfin() -> Jellyfin:
    """Create Jellyfin without running its network-backed initializer."""
    client = Jellyfin.__new__(Jellyfin)
    client._handler = Mock()
    client._user_list = {}
    client._library_list = {}
    client._kind = 'movie'
    client.map = Mock(side_effect=lambda item: item)
    return client


def test_get_items_empty_success_returns_empty_list() -> None:
    """Successful empty Jellyfin responses are not failures."""
    client = jellyfin()
    client._handler.get.return_value = response(200, {'Items': []})

    assert client._get_items({}) == []


def test_get_items_with_no_matching_items_returns_empty_list() -> None:
    """A successful search with no Jellyfin matches is an empty result."""
    client = jellyfin()
    client._handler.get.return_value = response(200, {'Items': []})

    assert client.get('no matching title') == []


@pytest.mark.parametrize('status', [0, 404, 500])
def test_get_items_failure_returns_none(status: int) -> None:
    """Transport and HTTP failures retain Jellyfin's failure sentinel."""
    client = jellyfin()
    client._handler.get.return_value = response(status)

    assert client._get_items({}) is None


def test_get_preserves_get_items_failure() -> None:
    """Public get must not turn a failed query into an empty collection."""
    client = jellyfin()
    client._get_items = Mock(return_value=None)

    assert client.get() is None


def test_get_users_transport_failure_is_distinct_from_empty_users() -> None:
    """User API connectivity failures have a clear initialization error."""
    client = jellyfin()
    client._handler.get.return_value = response(0)

    with pytest.raises(ValueError, match='Failed to query Jellyfin users: HTTP 0'):
        client._get_users()


def test_get_users_empty_success_has_empty_metadata_error() -> None:
    """An available user endpoint with no users keeps the empty-data error."""
    client = jellyfin()
    client.cfg = Mock(return_value=[])
    client._handler.get.return_value = response(200, [])

    with pytest.raises(ValueError, match='No users found in Jellyfin'):
        client._get_users()


def test_get_libraries_http_failure_is_distinct_from_empty_libraries() -> None:
    """Library API HTTP errors have a clear initialization error."""
    client = jellyfin()
    client._handler.get.return_value = response(500)

    with pytest.raises(ValueError, match='Failed to query Jellyfin libraries: HTTP 500'):
        client._get_libraries()


def test_get_libraries_empty_success_has_empty_metadata_error() -> None:
    """An available library endpoint with no libraries keeps the empty-data error."""
    client = jellyfin()
    client._handler.get.return_value = response(200, [])

    with pytest.raises(ValueError, match='No libraries found in Jellyfin'):
        client._get_libraries()


def test_inverse_empty_query_input_returns_empty_list() -> None:
    """An empty exclusion set remains protected from destructive inversion."""
    client = jellyfin()

    assert client._inverse_items([]) == []


def test_inverse_full_library_failure_returns_none() -> None:
    """A failed full-library lookup must not look like an empty library."""
    client = jellyfin()
    client._get_items = Mock(return_value=None)

    assert client._inverse_items([{'jellyfinid': 'included'}]) is None


def test_inverse_empty_full_library_returns_empty_list() -> None:
    """A successfully empty full library remains an empty inverse result."""
    client = jellyfin()
    client._get_items = Mock(return_value=[])

    assert client._inverse_items([{'jellyfinid': 'included'}]) == []
