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


def test_inverse_empty_query_input_returns_full_library() -> None:
    """The inverse of a successfully empty library is the full library."""
    client = jellyfin()
    library_items = [
        {'title': 'Supergirl', 'year': '2026', 'jellyfinid': 'library-copy'},
    ]
    client._get_items = Mock(return_value=library_items)

    assert client._inverse_items([]) == library_items


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


def test_inverse_uses_jellyfin_record_ids_for_library_membership() -> None:
    """Copies in separate libraries remain distinct despite shared provider IDs."""
    client = jellyfin()
    trending_copy = {
        'title': 'Supergirl', 'year': '2026', 'jellyfinid': 'trending-copy',
        'tmdbid': '400160', 'imdbid': '1234567',
    }
    library_copy = {
        'title': 'Supergirl', 'year': '2026', 'jellyfinid': 'library-copy',
        'tmdbid': '400160', 'imdbid': '1234567',
    }
    client._get_items = Mock(return_value=[trending_copy, library_copy])

    assert client._inverse_items([trending_copy]) == [library_copy]


def test_inverse_unique_excludes_media_found_outside_trending_library() -> None:
    """The import filter rejects media that has a distinct copy in another library."""
    client = jellyfin()
    client._library_list = {'Trending Filmek': 'trending'}
    trending_copy = {
        'title': 'Supergirl', 'year': '2026', 'jellyfinid': 'trending-copy',
        'tmdbid': '400160',
    }
    library_copy = {
        'title': 'Supergirl', 'year': '2026', 'jellyfinid': 'library-copy',
        'tmdbid': '400160',
    }
    client._get_items = Mock(side_effect=[
        [trending_copy],
        [trending_copy, library_copy],
    ])
    candidate = {'title': 'Supergirl', 'year': '2026', 'tmdbid': '400160'}
    query = {'parentLibrary': 'Trending Filmek', 'allUsers': True, 'isInverse': True}

    assert client.unique([candidate], query) == []
    assert client._get_items.call_args_list[1].kwargs['query'] == {'allUsers': True}


def test_inverse_common_selects_old_trending_item_for_cleanup() -> None:
    """A Trending placeholder is selected for removal after a real copy appears."""
    client = jellyfin()
    client._library_list = {'Trending Filmek': 'trending'}
    trending_copy = {
        'title': 'Supergirl', 'year': '2026', 'jellyfinid': 'trending-copy',
        'tmdbid': '400160',
    }
    library_copy = {
        'title': 'Supergirl', 'year': '2026', 'jellyfinid': 'library-copy',
        'tmdbid': '400160',
    }
    client._get_items = Mock(side_effect=[
        [trending_copy],
        [trending_copy, library_copy],
    ])
    local_placeholder = {
        'title': 'Supergirl', 'year': '2026', 'tmdbid': '400160',
    }
    query = {'parentLibrary': 'Trending Filmek', 'allUsers': True, 'isInverse': True}

    assert client.common([local_placeholder], query) == [local_placeholder]


def test_inverse_common_cleans_old_item_when_trending_query_is_empty() -> None:
    """Cleanup still finds external copies before Jellyfin indexes Trending."""
    client = jellyfin()
    client._library_list = {'Trending Filmek': 'trending'}
    library_copy = {
        'title': 'Supergirl', 'year': '2026', 'jellyfinid': 'library-copy',
        'tmdbid': '400160',
    }
    client._get_items = Mock(side_effect=[[], [library_copy]])
    local_placeholder = {
        'title': 'Supergirl', 'year': '2026', 'tmdbid': '400160',
    }
    query = {'parentLibrary': 'Trending Filmek', 'allUsers': True, 'isInverse': True}

    assert client.common([local_placeholder], query) == [local_placeholder]


def test_construction_does_not_contact_jellyfin(monkeypatch) -> None:
    """Users and libraries are loaded on first use, not by the constructor."""
    calls = []
    monkeypatch.setattr(Jellyfin, "_get_users", lambda self: calls.append("users") or {"user": "1"})
    monkeypatch.setattr(Jellyfin, "_get_libraries", lambda self: calls.append("libraries") or {"Movies": "9"})
    client = Jellyfin(config={"url": "http://jellyfin", "token": "token"})
    assert calls == []
    client._handler = Mock()
    client._handler.get.return_value = response(200, {"Items": []})

    assert client.get({"parentLibrary": "Movies"}) == []
    assert client.get({"parentLibrary": "Movies"}) == []
    assert calls == ["libraries", "users"]
    assert client._handler.get.call_args.kwargs["params"]["ParentId"] == "9"


def test_items_without_tmdb_id_are_kept_for_set_operations() -> None:
    """A Jellyfin movie without a TMDb provider ID is still part of the library."""
    client = Jellyfin.__new__(Jellyfin)
    client.name = "jellyfin"
    client._data_mappings = {
        "title": ["Name"], "year": ["ProductionYear"], "jellyfinid": ["Id"], "tmdbid": ["ProviderIds"],
    }
    client._data_transforms = {"tmdbid": lambda value: dict(value).get("Tmdb")}
    client._empty_property_allowed = False

    assert client.map({"Name": "Film", "ProductionYear": 2020, "Id": "1", "ProviderIds": {"Imdb": "tt1"}}) == {
        "title": "Film", "year": 2020, "jellyfinid": "1",
    }


def test_inverse_and_per_user_cannot_be_combined() -> None:
    with pytest.raises(ValueError, match="perUser"):
        jellyfin()._parse_query({"isInverse": True, "perUser": True})
