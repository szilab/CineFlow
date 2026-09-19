"""Regression tests for qBittorrent WebAPI support."""
# pylint: disable=protected-access,use-implicit-booleaness-not-comparison

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cineflow.integrations.qbittorrent import QBittorrent
from cineflow.utils.misc import load_module


def response(status: int, data=None, cookies=None, headers=None):
    """Create a minimal mocked request response."""
    return SimpleNamespace(status=status, data=data, cookies=cookies or {}, headers=headers or {})


def qbittorrent() -> QBittorrent:
    """Create QBittorrent without running its network-backed initializer."""
    client = QBittorrent.__new__(QBittorrent)
    client._handler = Mock()
    client._sid = 'old-sid'
    client._auth_cookies = {'SID': 'old-sid'}
    client._url = 'http://qbittorrent:8080'
    client._headers = {
        'Referer': 'http://qbittorrent:8080/',
        'Origin': 'http://qbittorrent:8080',
    }
    client.cfg = Mock(return_value=None)
    return client


def test_load_module_registers_qbittorrent() -> None:
    """The workflow loader can resolve the qBittorrent integration."""
    assert load_module("qbittorrent").__name__ == "QBittorrent"


def test_referer_is_derived_from_configured_base_url() -> None:
    """qBittorrent receives a same-origin Referer header."""
    client = qbittorrent()
    client._url = 'https://example.test:9443/qbit'

    assert client._referer() == 'https://example.test:9443/qbit/'
    assert client._origin() == 'https://example.test:9443'


def test_login_uses_form_data_and_sid_cookie() -> None:
    """qBittorrent authentication stores the returned cookie SID."""
    client = qbittorrent()
    client.cfg = Mock(
        side_effect=lambda key, default=None: {
            'username': 'user', 'password': 'pass'
        }.get(key, default)
    )
    client._handler.post.return_value = response(200, 'Ok.', {'SID': 'new-sid'})

    client._login()

    assert client._sid == 'new-sid'
    client._handler.post.assert_called_once_with(
        endpoint='api/v2/auth/login',
        data={'username': 'user', 'password': 'pass'},
        headers={
            'Referer': 'http://qbittorrent:8080/',
            'Origin': 'http://qbittorrent:8080',
            'Content-Type': 'application/x-www-form-urlencoded',
        },
    )


def test_login_accepts_no_content_response_with_sid_cookie() -> None:
    """Some qBittorrent deployments return 204 with only the session cookie."""
    client = qbittorrent()
    client.cfg = Mock(
        side_effect=lambda key, default=None: {
            'username': 'user', 'password': 'pass'
        }.get(key, default)
    )
    client._handler.post.return_value = response(204, None, {'SID': 'new-sid'})

    client._login()

    assert client._sid == 'new-sid'


def test_login_reads_sid_from_set_cookie_header() -> None:
    """Reverse-proxied qBittorrent logins may expose SID only in Set-Cookie."""
    client = qbittorrent()
    client.cfg = Mock(
        side_effect=lambda key, default=None: 'user' if key == 'username' else default
    )
    client._handler.post.return_value = response(
        204, headers={'Set-Cookie': 'SID=header-sid; Path=/'}
    )

    client._login()

    assert client._sid == 'header-sid'
    assert client._auth_cookies == {'SID': 'header-sid'}


def test_login_reuses_returned_qbt_sid_cookie_name() -> None:
    """qBittorrent may return a QBT_SID_* cookie name instead of SID."""
    client = qbittorrent()
    client.cfg = Mock(
        side_effect=lambda key, default=None: 'user' if key == 'username' else default
    )
    client._handler.post.return_value = response(204, cookies={'QBT_SID_8080': 'qbt-sid'})

    client._login()

    assert client._sid == 'qbt-sid'
    assert client._cookies() == {'QBT_SID_8080': 'qbt-sid'}


def test_login_failure_raises_value_error() -> None:
    """Invalid credentials fail during initialization instead of later as an empty list."""
    client = qbittorrent()
    client.cfg = Mock(
        side_effect=lambda key, default=None: 'user' if key == 'username' else default
    )
    client._handler.post.return_value = response(200, 'Fails.')

    with pytest.raises(ValueError, match='Failed to authenticate with qBittorrent: 200'):
        client._login()


@pytest.mark.parametrize('status', [401, 403])
def test_login_rejected_statuses_raise_value_error(status: int) -> None:
    """Newer qBittorrent auth failures remain clear initialization errors."""
    client = qbittorrent()
    client.cfg = Mock(
        side_effect=lambda key, default=None: 'user' if key == 'username' else default
    )
    client._handler.post.return_value = response(status)

    with pytest.raises(ValueError, match=f'Failed to authenticate with qBittorrent: {status}'):
        client._login()


def test_no_content_login_without_sid_cookie_raises_value_error() -> None:
    """A credentialed qBittorrent login must provide a usable SID."""
    client = qbittorrent()
    client.cfg = Mock(
        side_effect=lambda key, default=None: 'user' if key == 'username' else default
    )
    client._handler.post.return_value = response(204)

    with pytest.raises(ValueError, match='Failed to authenticate with qBittorrent: 204'):
        client._login()


def test_ok_login_without_sid_cookie_raises_value_error() -> None:
    """A 200 Ok. login response must include SID to be usable."""
    client = qbittorrent()
    client.cfg = Mock(
        side_effect=lambda key, default=None: 'user' if key == 'username' else default
    )
    client._handler.post.return_value = response(200, 'Ok.')

    with pytest.raises(ValueError, match='Failed to authenticate with qBittorrent: 200'):
        client._login()


def test_api_request_retries_once_after_forbidden_with_credentials() -> None:
    """One 403 triggers one login refresh and one retry."""
    client = qbittorrent()
    client.cfg = Mock(
        side_effect=lambda key, default=None: 'user' if key == 'username' else default
    )
    client._send_request = Mock(side_effect=[response(403), response(200, [])])
    client._login = Mock()

    assert client._api_request('GET', 'api/v2/torrents/info') == []
    assert client._send_request.call_count == 2
    client._login.assert_called_once_with()


def test_api_request_stops_after_one_forbidden_retry() -> None:
    """Repeated 403 responses never recurse or retry indefinitely."""
    client = qbittorrent()
    client.cfg = Mock(
        side_effect=lambda key, default=None: 'user' if key == 'username' else default
    )
    client._send_request = Mock(side_effect=[response(403), response(403)])
    client._login = Mock()

    assert client._api_request('GET', 'api/v2/torrents/info') is None
    assert client._send_request.call_count == 2
    client._login.assert_called_once_with()


def test_api_request_returns_none_when_reauthentication_fails() -> None:
    """A failed re-login is an API failure, not an unbounded retry."""
    client = qbittorrent()
    client.cfg = Mock(
        side_effect=lambda key, default=None: 'user' if key == 'username' else default
    )
    client._send_request = Mock(return_value=response(403))
    client._login = Mock(side_effect=ValueError('Failed to authenticate with qBittorrent: 403'))

    assert client._api_request('GET', 'api/v2/torrents/info') is None
    assert client._send_request.call_count == 1
    client._login.assert_called_once_with()


def test_api_request_does_not_retry_without_credentials() -> None:
    """403 without configured credentials remains a failed request."""
    client = qbittorrent()
    client._send_request = Mock(return_value=response(403))
    client._login = Mock()

    assert client._api_request('GET', 'api/v2/torrents/info') is None
    assert client._send_request.call_count == 1
    client._login.assert_not_called()


def test_get_preserves_failure_and_empty_success_semantics() -> None:
    """qBittorrent failures return None while successful empty responses return an empty list."""
    client = qbittorrent()
    client._api_request = Mock(side_effect=[None, [], {}])

    assert client.get() is None
    assert client.get() == []
    assert client.get() is None


def test_get_filters_torrents_and_search_uses_alternate_title() -> None:
    """Torrent results are mapped, filtered, and searched by alternate title."""
    client = qbittorrent()
    client._api_request = Mock(return_value=[
        {'name': 'Film.Name.2024.1080p', 'state': 'uploading', 'progress': 1},
        {'name': 'Other.2023.720p', 'state': 'downloading', 'progress': 0.5},
    ])
    client._data_mappings = {
        'title': ['name'],
        'year': ['name'],
        'status': ['state'],
        'percent_done': ['progress'],
    }
    client._data_transforms = {
        'title': lambda value: value.split('.')[0],
        'year': lambda value: value.split('.')[2],
    }
    client._empty_property_allowed = False

    assert client.get('Film') == [
        {'title': 'Film', 'year': '2024', 'status': 'uploading', 'percent_done': 1}
    ]
    client.get = Mock(
        side_effect=[[{'title': 'Alt', 'year': 2024}], [{'title': 'Alt', 'year': 2024}]]
    )
    client.match = Mock(side_effect=[None, {'title': 'Alt', 'year': 2024}])
    assert client.search({'title': 'Film', 'alttitle': 'Alt', 'year': 2024})['title'] == 'Alt'


def test_put_prepares_url_forms_without_downloading_torrents() -> None:
    """Magnet and HTTP links are sent directly to qBittorrent as URL form data."""
    client = qbittorrent()
    values = {
        'directory': '/downloads',
        'category': 'movies',
        'tags': 'cineflow,auto',
    }
    client.cfg = Mock(side_effect=lambda key, default=None: values.get(key, default))

    assert client._prepare_params({'title': 'Film', 'link': 'magnet:?xt=1'}) == {
        'urls': 'magnet:?xt=1',
        'savepath': '/downloads',
        'category': 'movies',
        'tags': 'cineflow,auto',
    }
    params = client._prepare_params({'title': 'Film', 'link': 'https://example/torrent'})
    assert params['urls'] == 'https://example/torrent'
    media = {'title': 'Film', 'link': 'ftp://unsupported'}
    assert client._prepare_params(media) is None
    assert media['qbittorrent_status'] == 'invalid_link'


def test_put_records_qbittorrent_outcomes() -> None:
    """Adding data delegates valid inputs and records per-item qBittorrent status."""
    client = qbittorrent()
    client._prepare_params = Mock(side_effect=[
        {'urls': 'magnet'}, {'urls': 'magnet'}, {'urls': 'magnet'},
        {'urls': 'magnet'}, None,
    ])
    client._api_request = Mock(side_effect=['Ok.', 'Fails.', {'success_count': 1}, None])
    data = [
        {'title': 'Added'}, {'title': 'Failed'}, {'title': 'Structured'},
        {'title': 'Error'}, {'title': 'Skipped'},
    ]

    assert client.put(data) == data
    assert data[0]['qbittorrent_status'] == 'added'
    assert data[1]['qbittorrent_status'] == 'error'
    assert data[2]['qbittorrent_status'] == 'added'
    assert data[3]['qbittorrent_status'] == 'error'
    assert 'qbittorrent_status' not in data[4]
    assert client.put([]) == []


def test_handle_response_maps_structured_failures_and_pending_adds() -> None:
    """WebAPI 2.14+ add responses are interpreted without assuming 409 means duplicate."""
    client = qbittorrent()
    failure = {'title': 'Failure'}
    pending = {'title': 'Pending'}

    client._handle_response(failure, {'success_count': 0, 'pending_count': 0, 'failure_count': 1})
    client._handle_response(pending, {'success_count': 0, 'pending_count': 1, 'failure_count': 0})

    assert failure['qbittorrent_status'] == 'error'
    assert pending['qbittorrent_status'] == 'added'


def test_send_request_uses_multipart_fields_referer_and_sid_cookie() -> None:
    """qBittorrent torrent-add endpoints use documented multipart form fields."""
    client = qbittorrent()
    client._handler.post.return_value = response(200, 'Ok.')

    client._send_request(
        'POST', 'api/v2/torrents/add', data={'urls': 'magnet', 'category': 'movies'}, form=True
    )

    client._handler.post.assert_called_once_with(
        endpoint='api/v2/torrents/add',
        data={},
        cookies={'SID': 'old-sid'},
        headers={
            'Referer': 'http://qbittorrent:8080/',
            'Origin': 'http://qbittorrent:8080',
        },
        files={'urls': (None, 'magnet'), 'category': (None, 'movies')},
    )
