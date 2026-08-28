"""Regression tests for Transmission RPC session handling."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cineflow.integrations.transmission import Transmission


def response(status: int, data=None, headers=None):
    """Create a minimal mocked request response."""
    return SimpleNamespace(status=status, data=data, headers=headers or {})


def transmission() -> Transmission:
    """Create Transmission without running its network-backed initializer."""
    client = Transmission.__new__(Transmission)
    client._handler = Mock()
    client._auth = None
    client._session_id = 'old-session'
    client.cfg = Mock(return_value='transmission/rpc')
    return client


def test_rpc_retries_once_after_session_refresh() -> None:
    """One 409 refreshes the session and permits one successful retry."""
    client = transmission()
    client._handler.post.side_effect = [
        response(409), response(200, {'arguments': {'torrents': []}, 'result': 'success'}),
    ]
    client._get_session_id = Mock(return_value='new-session')

    assert client._rpc_request('torrent-get') == {'torrents': [], 'result': 'success'}
    assert client._handler.post.call_count == 2
    client._get_session_id.assert_called_once_with()


def test_rpc_stops_after_second_409() -> None:
    """A repeated session conflict never recurses or retries indefinitely."""
    client = transmission()
    client._handler.post.side_effect = [response(409), response(409)]
    client._get_session_id = Mock(return_value='new-session')

    assert client._rpc_request('torrent-get') == {}
    assert client._handler.post.call_count == 2
    client._get_session_id.assert_called_once_with()


def test_session_id_is_read_from_409_response_header() -> None:
    """Transmission returns valid session IDs on 409 responses."""
    client = transmission()
    client._handler.post.return_value = response(409, headers={'X-Transmission-Session-Id': 'abc123'})

    assert client._get_session_id() == 'abc123'


def test_session_id_without_header_raises_value_error() -> None:
    """A session response without the required header remains invalid."""
    client = transmission()
    client._handler.post.return_value = response(409)

    with pytest.raises(ValueError, match='Failed to get session ID: 409'):
        client._get_session_id()


def test_handle_response_marks_failed_torrent_add_as_error() -> None:
    """Failed RPC adds retain the existing per-item error status."""
    client = transmission()
    media = {'title': 'Example'}

    client._handle_response(media, {})

    assert media['transmission_status'] == 'error'


def test_get_filters_torrents_and_search_uses_alternate_title() -> None:
    """Torrent results are mapped, filtered, and searched by alternate title."""
    client = transmission()
    client._rpc_request = Mock(return_value={"torrents": [
        {"name": "Film.Name.2024.1080p", "status": 4, "percentDone": 1},
        {"name": "Other.2023.720p", "status": 4, "percentDone": 1},
    ]})
    client._data_mappings = {"title": ["name"], "year": ["name"]}
    client._data_transforms = {"title": lambda value: value.split(".")[0], "year": lambda value: value.split(".")[2]}
    client._empty_property_allowed = False
    assert client.get("Film") == [{"title": "Film", "year": "2024"}]
    client.get = Mock(side_effect=[[{"title": "Alt", "year": 2024}], [{"title": "Alt", "year": 2024}]])
    client.match = Mock(side_effect=[None, {"title": "Alt", "year": 2024}])
    assert client.search({"title": "Film", "alttitle": "Alt", "year": 2024})["title"] == "Alt"


def test_put_prepares_magnet_and_http_torrents(monkeypatch) -> None:
    """Download input is converted to the RPC forms accepted by Transmission."""
    client = transmission()
    client.cfg = Mock(side_effect=lambda key, default=None: "/downloads" if key == "directory" else default)
    assert client._prepare_params({"title": "Film"}) is None
    assert client._prepare_params({"title": "Film", "link": "magnet:?xt=1"}) == {
        "download-dir": "/downloads", "filename": "magnet:?xt=1"
    }

    class Download:
        content = b"d8:announce-test"
        headers = {"Content-Type": "application/x-bittorrent"}

        def raise_for_status(self):
            pass
    monkeypatch.setattr("cineflow.integrations.transmission.requests.get", lambda *args, **kwargs: Download())
    assert "metainfo" in client._prepare_params({"title": "Film", "link": "https://torrent"})
    media = {"title": "Film", "link": "ftp://unsupported"}
    assert client._prepare_params(media) is None


def test_put_records_rpc_outcomes() -> None:
    """Adding data delegates valid inputs and records the resulting status."""
    client = transmission()
    client._prepare_params = Mock(side_effect=[{"filename": "magnet"}, None])
    client._rpc_request = Mock(return_value={"torrent-added": {"id": 1}})
    data = [{"title": "Film"}, {"title": "Skipped"}]
    assert client.put(data) == data
    assert data[0]["transmission_status"] == "added"
    assert client.put([]) == []
