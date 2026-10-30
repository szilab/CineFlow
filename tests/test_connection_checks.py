"""Connection tests of the integrations, with mocked transports."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cineflow.integrations.jackett import Jackett
from cineflow.integrations.jellyfin import Jellyfin
from cineflow.integrations.plex import Plex
from cineflow.integrations.qbittorrent import QBittorrent
from cineflow.integrations.tmdb import Tmdb
from cineflow.integrations.transmission import Transmission


@pytest.mark.parametrize(('client', 'endpoint'), [
    (lambda: Tmdb(config={'token': 't'}), '/configuration'),
    (lambda: Jackett(config={'url': 'http://j', 'token': 't'}), '/api/v2.0/indexers/all/results/torznab/api'),
    (lambda: Jellyfin(config={'url': 'http://j', 'token': 't'}), '/System/Info'),
    (lambda: Plex(config={'url': 'http://p', 'token': 't'}), '/library/sections'),
])
@pytest.mark.parametrize(('status', 'ok', 'text'), [
    (200, True, 'Connected'), (0, False, 'unreachable'), (401, False, 'Authentication'),
    (500, False, 'Unexpected'),
])
def test_http_connection_checks(client, endpoint: str, status: int, ok: bool, text: str) -> None:
    module = client()
    module._handler = Mock()
    module._handler.get.return_value = SimpleNamespace(status=status, data=None)

    result = module.check_connection()

    assert result['ok'] is ok and text in result['message']
    call = module._handler.get.call_args.kwargs
    assert call['endpoint'] == endpoint and call['cache_time'] == 0


def test_check_without_endpoint_is_unsupported() -> None:
    module = Tmdb(config={'token': 't'})
    module.CHECK_ENDPOINT = ''
    assert module.check_connection()['ok'] is False


def test_transmission_check(monkeypatch: pytest.MonkeyPatch) -> None:
    client = Transmission(config={'url': 'http://tr'})
    monkeypatch.setattr(client, '_get_session_id', Mock(return_value='sid'))
    monkeypatch.setattr(client, '_rpc_request', Mock(return_value={'version': '4'}))
    assert client.check_connection()['ok'] is True

    client._rpc_request.return_value = None
    assert client.check_connection()['ok'] is False

    client._get_session_id.side_effect = ValueError('Failed to get session ID: 0')
    assert client.check_connection() == {'ok': False, 'message': 'Failed to get session ID: 0'}


def test_qbittorrent_check(monkeypatch: pytest.MonkeyPatch) -> None:
    client = QBittorrent(config={'url': 'http://qb'})
    monkeypatch.setattr(client, '_api_request', Mock(return_value='v5.0.0'))
    assert client.check_connection() == {'ok': True, 'message': 'Connected to qBittorrent v5.0.0.'}

    client._api_request.return_value = None
    assert client.check_connection()['ok'] is False
