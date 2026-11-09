"""Regression tests for Jellyfin folder names of torrent downloads and the wait step."""
# pylint: disable=protected-access

import base64
import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from cineflow.core import validation
from cineflow.integrations.qbittorrent import QBittorrent
from cineflow.integrations.transmission import Transmission
from cineflow.internal.tools import Tools
from cineflow.utils import torrent
from cineflow.utils.misc import jellyfin_name, release_parsers
from cineflow.utils.torrent import (
    folder_plan, info_hash, join_path, link_hash, magnet_hash, media_folder, path_name, same_path,
)

HASH = 'c12fe1c06bba254a9dc9f519b335aa7c1367a88a'
INFO = b'd6:lengthi10e4:name8:film.mkv12:piece lengthi16384e6:pieces20:aaaaaaaaaaaaaaaaaaaae'
TORRENT = b'd8:announce14:http://tracker4:info' + INFO + b'e'
MOVIE = {'title': 'Mission: Impossible', 'year': 1996, 'tmdbid': 954, 'link': f'magnet:?xt=urn:btih:{HASH}'}


def response(status: int, data=None):
    """Create a minimal mocked request response."""
    return SimpleNamespace(status=status, data=data, headers={}, cookies={})


# ---- helpers ----

@pytest.mark.parametrize('media, expected', [
    (MOVIE, 'Mission Impossible (1996) [tmdbid-954]'),
    ({'title': 'Show', 'tmdbid': 7}, 'Show [tmdbid-7]'),
    ({'title': 'Film', 'year': 2020}, 'Film (2020)'),
    ({'title': 'Dr. '}, 'Dr'),
    ({'title': ''}, None),
    ({}, None),
])
def test_media_folder_names(media, expected) -> None:
    """The folder name follows the Jellyfin 'Title (year) [tmdbid-N]' convention."""
    assert media_folder(media) == expected


def test_media_folder_suffix_inserts_item_fields() -> None:
    """The suffix follows the generated name; {field} inserts item values, unknown ones are empty."""
    media = {**MOVIE, 'resolution': '2160p', 'episodes': [1, 2]}
    base = 'Mission Impossible (1996) [tmdbid-954]'
    assert media_folder(media, suffix=' - {resolution}') == f'{base} - 2160p'
    assert media_folder(media, suffix=' [{resolution}] E{episodes}') == f'{base} [2160p] E1,2'
    assert media_folder(media, suffix=' {missing}') == base
    assert media_folder(media, suffix=' a/b: {resolution}.') == f'{base} ab 2160p'
    assert media_folder({'title': ''}, suffix=' x') is None


@pytest.mark.parametrize('files, expected', [
    ([], ('wait', None)),
    (None, ('wait', None)),
    (['Film.2020/film.mkv', 'Film.2020/Sample/sample.mkv'], ('rename', 'Film.2020')),
    (['Film (2020)/film.mkv'], ('done', 'Film (2020)')),
    (['film.mkv'], ('move', None)),
    (['a.mkv', 'b.nfo'], ('move', None)),
    (['Root\\film.mkv'], ('rename', 'Root')),
])
def test_folder_plan(files, expected) -> None:
    """The plan depends on whether the torrent has metadata and a root folder."""
    assert folder_plan(files, 'Film (2020)') == expected


def test_client_path_helpers() -> None:
    """Paths of the client machine keep their separator and compare without a trailing one."""
    assert join_path('/downloads/', 'Film') == '/downloads/Film'
    assert join_path('D:\\Downloads', 'Film') == 'D:\\Downloads\\Film'
    assert same_path('/downloads/Film/', '/downloads/Film')
    assert same_path('D:\\Downloads\\Film', 'D:/Downloads/Film')
    assert not same_path('', '')
    assert path_name('/downloads/Film/') == 'Film'


def test_magnet_hash_reads_hex_and_base32() -> None:
    """Hex and base32 v1 hashes are returned as lowercase hex."""
    assert magnet_hash(f'magnet:?dn=x&xt=urn:btih:{HASH.upper()}') == HASH
    base32 = base64.b32encode(bytes.fromhex(HASH)).decode()
    assert magnet_hash(f'magnet:?xt=urn:btih:{base32}') == HASH
    assert magnet_hash('magnet:?xt=urn:btmh:1220abcd') is None
    assert magnet_hash('magnet:?xt=urn:btih:short') is None
    assert magnet_hash('http://x') is None
    assert magnet_hash(None) is None


def test_info_hash_hashes_the_info_dictionary() -> None:
    """The v1 info hash is the SHA-1 of the bencoded info dictionary."""
    assert info_hash(TORRENT) == hashlib.sha1(INFO).hexdigest()
    assert info_hash(b'd8:announce3:urle') is None
    assert info_hash(b'<html>') is None
    assert info_hash(b'd4:infod4:name99:x') is None
    assert info_hash(b'd4:infoxe') is None
    assert info_hash(b'') is None


def test_link_hash_reads_magnets_files_and_redirects(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP links are downloaded; a redirect to a magnet link gives the magnet hash."""
    assert link_hash(MOVIE['link']) == HASH
    assert link_hash('ftp://x') is None
    assert link_hash('') is None

    file = SimpleNamespace(is_redirect=False, content=TORRENT, raise_for_status=lambda: None)
    monkeypatch.setattr(torrent.requests, 'get', lambda *args, **kwargs: file)
    assert link_hash('http://jackett/dl') == hashlib.sha1(INFO).hexdigest()

    redirect = SimpleNamespace(is_redirect=True, headers={'Location': MOVIE['link']})
    monkeypatch.setattr(torrent.requests, 'get', lambda *args, **kwargs: redirect)
    assert link_hash('http://jackett/dl') == HASH

    loop = SimpleNamespace(is_redirect=True, headers={'Location': '/again'})
    monkeypatch.setattr(torrent.requests, 'get', lambda *args, **kwargs: loop)
    assert link_hash('http://jackett/dl') is None

    def fail(*args, **kwargs):
        raise requests.ConnectionError('down')
    monkeypatch.setattr(torrent.requests, 'get', fail)
    assert link_hash('http://jackett/dl') is None


# ---- Transmission ----

def transmission(torrents: dict, others: list | None = None) -> Transmission:
    """Create Transmission whose RPC answers from ``torrents`` (hash -> torrent)."""
    client = Transmission.__new__(Transmission)
    client.name = 'transmission'
    client._cfg = {}
    client.calls = []

    def rpc(method: str, params: dict = None):
        client.calls.append((method, params))
        if method == 'torrent-get' and 'ids' in params:
            return {'torrents': [torrents[h] for h in params['ids'] if h in torrents], 'result': 'success'}
        if method == 'torrent-get':
            return None if others is None else {'torrents': others, 'result': 'success'}
        return {'result': 'success'}
    client._rpc_request = rpc
    return client


def added(**extra) -> dict:
    return {**MOVIE, 'transmission_status': 'added', 'torrent_hash': HASH, **extra}


def test_transmission_put_records_the_torrent_hash() -> None:
    """The add response carries the hash the rename step needs."""
    client = Transmission.__new__(Transmission)
    media = {'title': 'Film'}
    client._handle_response(media, {'torrent-added': {'id': 1, 'hashString': HASH}})
    assert media == {'title': 'Film', 'torrent_hash': HASH, 'transmission_status': 'added'}
    media = {'title': 'Film'}
    client._handle_response(media, {'torrent-duplicate': {'id': 1, 'hashString': HASH}})
    assert media['torrent_hash'] == HASH and media['transmission_status'] == 'duplicate'
    media = {'title': 'Film'}
    client._handle_response(media, None)
    assert 'torrent_hash' not in media


def test_transmission_renames_the_root_folder() -> None:
    """A torrent with a root folder gets it renamed."""
    state = {'id': 5, 'downloadDir': '/dl', 'files': [{'name': 'MI.1996.1080p/mi.mkv'}]}
    client = transmission({HASH: state}, others=[{'name': 'MI.1996.1080p', 'downloadDir': '/dl'}])
    data = [added()]

    assert client.rename(data) == data
    assert data[0]['transmission_folder'] == 'renamed'
    assert client.calls[-1] == ('torrent-rename-path', {
        'ids': [5], 'path': 'MI.1996.1080p', 'name': 'Mission Impossible (1996) [tmdbid-954]'})


def test_rename_uses_the_suffix_of_the_step() -> None:
    """The step's suffix is part of the folder name."""
    state = {'id': 5, 'downloadDir': '/dl', 'files': [{'name': 'MI.1996.1080p/mi.mkv'}]}
    client = transmission({HASH: state}, others=[])
    client._cfg = {'suffix': ' - {resolution}'}
    data = [added(resolution='1080p')]

    client.rename(data)
    assert client.calls[-1][1]['name'] == 'Mission Impossible (1996) [tmdbid-954] - 1080p'


def test_transmission_moves_a_single_file_into_a_folder() -> None:
    """A torrent of one file moves into a new folder, the file keeps its name."""
    state = {'id': 5, 'downloadDir': '/dl/', 'files': [{'name': 'Show.S01E02.mkv'}]}
    client = transmission({HASH: state})
    data = [added(title='Show', year=2020, tmdbid=1)]

    client.rename(data)
    assert data[0]['transmission_folder'] == 'moved'
    assert client.calls[-1] == ('torrent-set-location', {
        'ids': [5], 'location': '/dl/Show (2020) [tmdbid-1]', 'move': True})


def test_transmission_moves_into_a_folder_another_download_uses() -> None:
    """An other release of the same series goes into the existing folder, nothing is overwritten."""
    target = 'Show (2020) [tmdbid-1]'
    state = {'id': 5, 'downloadDir': '/dl', 'files': [{'name': 'Show.S01E03/e3.mkv'}]}
    for others in ([{'name': target, 'downloadDir': '/dl'}], [{'name': 'e1.mkv', 'downloadDir': f'/dl/{target}'}]):
        client = transmission({HASH: state}, others=others)
        data = [added(title='Show', year=2020, tmdbid=1)]
        client.rename(data)
        assert data[0]['transmission_folder'] == 'moved'
        assert client.calls[-1][0] == 'torrent-set-location'


def test_transmission_leaves_named_pending_and_unknown_torrents() -> None:
    """Named folders, missing metadata, failures and items not added change nothing."""
    target = 'Mission Impossible (1996) [tmdbid-954]'
    cases = [
        ({'id': 5, 'downloadDir': '/dl', 'files': [{'name': f'{target}/mi.mkv'}]}, 'done'),
        ({'id': 5, 'downloadDir': f'/dl/{target}', 'files': [{'name': 'mi.mkv'}]}, 'done'),
        ({'id': 5, 'downloadDir': '/dl', 'files': []}, 'pending'),
    ]
    for state, outcome in cases:
        client = transmission({HASH: state})
        data = [added()]
        client.rename(data)
        assert data[0]['transmission_folder'] == outcome
        assert all(method == 'torrent-get' for method, _ in client.calls)

    client = transmission({})
    data = [added(), added(torrent_hash=None), {**MOVIE, 'transmission_status': 'error'}, added(title='')]
    client.rename(data)
    assert [item.get('transmission_folder') for item in data] == ['error', 'error', None, None]
    assert client.rename(None) is None


def test_transmission_rename_fails_closed() -> None:
    """Unavailable torrent lists and refused renames or moves are errors."""
    state = {'id': 5, 'downloadDir': '/dl', 'files': [{'name': 'MI/mi.mkv'}]}
    client = transmission({HASH: state}, others=None)
    data = [added()]
    client.rename(data)
    assert data[0]['transmission_folder'] == 'error'
    assert not any(method != 'torrent-get' for method, _ in client.calls)

    client = transmission({HASH: state}, others=[])
    client._rename_root = Mock(return_value=False)
    client.rename(data)
    assert data[0]['transmission_folder'] == 'error'

    client = transmission({HASH: {**state, 'files': [{'name': 'mi.mkv'}]}})
    client._move_content = Mock(return_value=False)
    client.rename(data)
    assert data[0]['transmission_folder'] == 'error'


def test_transmission_rpc_failures_are_not_success() -> None:
    """The primitives report RPC failures."""
    client = Transmission.__new__(Transmission)
    client._rpc_request = Mock(return_value=None)
    assert client._torrent_state(HASH) is None
    assert client._torrent_locations() is None
    assert not client._rename_root({'id': 1}, 'a', 'b')
    assert not client._move_content({'id': 1}, '/dl/b')
    client._rpc_request = Mock(return_value={'torrents': ['bad'], 'result': 'success'})
    assert client._torrent_state(HASH) is None
    assert client._torrent_locations() == []


# ---- qBittorrent ----

def qbittorrent(info: list | None, files: list | None, everything: list | None = None,
                status: int = 200) -> QBittorrent:
    """Create qBittorrent with mocked WebAPI answers."""
    client = QBittorrent.__new__(QBittorrent)
    client.name = 'qbittorrent'
    client._cfg = {}
    client.posts = []

    def api_response(method, endpoint, data=None, form=False):
        if method == 'POST':
            client.posts.append((endpoint, data))
            return response(status, '')
        if endpoint.startswith('api/v2/torrents/info?hashes='):
            return response(200, info)
        if endpoint.startswith('api/v2/torrents/files?hash='):
            return response(200, files)
        if endpoint == 'api/v2/torrents/info':
            return None if everything is None else response(200, everything)
        raise AssertionError(endpoint)
    client._api_response = api_response
    return client


def queued(**extra) -> dict:
    return {**MOVIE, 'qbittorrent_status': 'added', **extra}


def test_qbittorrent_renames_the_folder_found_by_the_magnet_hash() -> None:
    """The hash comes from the magnet link; renameFolder keeps the torrent name."""
    client = qbittorrent([{'save_path': '/dl'}], [{'name': 'MI.1996/mi.mkv'}],
                         everything=[{'save_path': '/dl', 'content_path': '/dl/MI.1996'}])
    data = [queued()]

    client.rename(data)
    assert data[0]['qbittorrent_folder'] == 'renamed'
    assert data[0]['torrent_hash'] == HASH
    assert client.posts == [('api/v2/torrents/renameFolder', {
        'hash': HASH, 'oldPath': 'MI.1996', 'newPath': 'Mission Impossible (1996) [tmdbid-954]'})]


def test_qbittorrent_moves_single_files_and_reports_refusals() -> None:
    """A single file moves with setLocation; a refused request is an error."""
    client = qbittorrent([{'save_path': '/dl'}], [{'name': 'mi.mkv'}])
    data = [queued()]
    client.rename(data)
    assert data[0]['qbittorrent_folder'] == 'moved'
    assert client.posts == [('api/v2/torrents/setLocation', {
        'hashes': HASH, 'location': '/dl/Mission Impossible (1996) [tmdbid-954]'})]

    client = qbittorrent([{'save_path': '/dl'}], [{'name': 'MI/mi.mkv'}], everything=[], status=409)
    data = [queued()]
    client.rename(data)
    assert data[0]['qbittorrent_folder'] == 'error'
    client._api_response = Mock(return_value=None)
    assert not client._move_content({'id': HASH}, '/dl/x')


def test_qbittorrent_unknown_or_unavailable_torrents_change_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing torrents, file lists or hashes leave the download alone."""
    for info, files, everything in (([], [], []), ([{'save_path': '/dl'}], None, []),
                                    ([{'save_path': '/dl'}], [{'name': 'MI/mi.mkv'}], None)):
        client = qbittorrent(info, files, everything)
        data = [queued()]
        client.rename(data)
        assert data[0]['qbittorrent_folder'] == 'error'
        assert client.posts == []

    monkeypatch.setattr('cineflow.integrations.qbittorrent.link_hash', lambda link: None)
    client = qbittorrent([], [])
    data = [queued(link='http://jackett/dl')]
    client.rename(data)
    assert data[0]['qbittorrent_folder'] == 'error'
    assert 'torrent_hash' not in data[0]


def test_qbittorrent_api_request_still_returns_data() -> None:
    """The data helper keeps returning the response data or None."""
    client = QBittorrent.__new__(QBittorrent)
    client._api_response = Mock(return_value=response(200, ['x']))
    assert client._api_request('GET', 'api/v2/torrents/info') == ['x']
    client._api_response = Mock(return_value=None)
    assert client._api_request('GET', 'api/v2/torrents/info') is None


# ---- wait step and flow ----

def test_wait_sleeps_only_with_items(monkeypatch: pytest.MonkeyPatch) -> None:
    """The wait passes items on after the clamped time; without items it returns at once."""
    sleeps = []
    monkeypatch.setattr('cineflow.internal.tools.time.sleep', sleeps.append)
    tools = Tools()
    items = [{'title': 'Film'}]

    assert tools.wait(items) is items
    assert tools.wait(items, seconds=999) is items
    assert tools.wait(items, seconds=0) is items
    assert tools.wait([]) == []
    assert tools.wait() is None
    assert sleeps == [10, 300, 1]


def test_flow_with_wait_and_rename_steps_is_valid() -> None:
    """A download flow can wait for the metadata and rename the folders."""
    data = {'name': 'F', 'kind': 'movie', 'steps': [
        {'name': 'trending', 'module': 'tmdb', 'action': 'get'},
        {'name': 'releases', 'module': 'jackett', 'action': 'enrich', 'input': 'previous'},
        {'name': 'download', 'module': 'transmission', 'action': 'put', 'input': 'previous'},
        {'name': 'metadata', 'module': 'tools', 'action': 'wait', 'input': {'data': 'previous', 'seconds': 20}},
        {'name': 'folders', 'module': 'transmission', 'action': 'rename', 'input': 'previous'},
        {'name': 'q', 'module': 'qbittorrent', 'action': 'rename', 'input': '{{download}}'},
    ]}
    config = {'tmdb': {'token': 'k'}, 'jackett': {'url': 'http://j', 'token': 'k'},
              'transmission': {'url': 'http://t'}, 'qbittorrent': {'url': 'http://q'}}
    assert [issue for issue in validation.validate_flow(data, config) if issue.level == 'error'] == []
    data['steps'][3]['input']['seconds'] = 301
    assert [issue.code for issue in validation.validate_flow(data, config) if issue.level == 'error'] == ['range']


# ---- reading renamed torrents back ----

@pytest.mark.parametrize('name, expected', [
    ('Mission Impossible (1996) [tmdbid-954]', {'title': 'Mission Impossible', 'year': '1996', 'tmdbid': 954}),
    ('Show [tmdbid-7]', {'title': 'Show', 'year': None, 'tmdbid': 7}),
    ('Film (2020)', {'title': 'Film', 'year': '2020', 'tmdbid': None}),
    ('Film.2020.1080p', None),
    ('Film (2020) 1080p', {'title': 'Film', 'year': '2020', 'tmdbid': None}),
    ('Film (2020) [tmdbid-5] - 1080p', {'title': 'Film', 'year': '2020', 'tmdbid': 5}),
    ('Show [tmdbid-7] HUN', {'title': 'Show', 'year': None, 'tmdbid': 7}),
    ('Film (Final Cut)', None),
    ('', None),
    (None, None),
])
def test_jellyfin_name(name, expected) -> None:
    """Jellyfin folder names are parsed; release names are not."""
    assert jellyfin_name(name) == expected


def test_release_parsers_read_folder_names_only_when_asked() -> None:
    """Download clients read renamed torrents; release names parse as before."""
    _, movie = release_parsers(kind='movie', source='name', folder_names=True)
    assert movie['title']('Film (2020) [tmdbid-5] - 1080p') == 'Film'
    assert movie['tmdbid']('Film (2020) [tmdbid-5] - 1080p') == 5
    assert movie['title']('Alien 3 (1992) 1080p') == 'Alien 3'

    _, plain = release_parsers(kind='movie', source='name')
    assert 'tmdbid' not in plain
    assert plain['title']('Mission Impossible (1996) [tmdbid-954]') is None

    _, movie = release_parsers(kind='movie', source='name', folder_names=True)
    name = 'Mission Impossible (1996) [tmdbid-954]'
    assert {key: parse(name) for key, parse in movie.items()} == {
        'title': 'Mission Impossible', 'year': '1996', 'tmdbid': 954}
    assert {key: parse('Mission.Impossible.1996.1080p') for key, parse in movie.items()} == {
        'title': 'Mission Impossible', 'year': '1996', 'tmdbid': None}

    _, series = release_parsers(kind='tv', source='name', folder_names=True)
    assert series['title']('Show (2020) [tmdbid-1]') == 'Show'
    assert series['season']('Show (2020) [tmdbid-1]') is None
    assert series['season']('Show.S02E03.1080p') == 2
    assert series['tmdbid']('Show.S02E03.1080p') is None


@pytest.mark.parametrize('client_class, kind', [
    (Transmission, 'movie'), (Transmission, 'tv'), (QBittorrent, 'movie'), (QBittorrent, 'tv'),
])
def test_clients_list_renamed_torrents(client_class, kind) -> None:
    """A renamed torrent stays in the client's list with its TMDb ID, so it is not downloaded again."""
    client = client_class(config={'url': 'http://client', 'kind': kind})
    renamed = {'name': 'Mission Impossible (1996) [tmdbid-954]', 'status': 6, 'state': 'uploading',
               'percentDone': 1, 'progress': 1}
    release = {**renamed, 'name': 'Show.S01E02.1080p' if kind == 'tv' else 'Other.Film.2001.1080p'}

    items = client._map_torrents(items=[renamed, release])
    assert items[0]['title'] == 'Mission Impossible'
    assert items[0]['year'] == '1996'
    assert items[0]['tmdbid'] == 954
    assert 'tmdbid' not in items[1]
    assert client.match(results=items, media={'title': 'Mission: Impossible', 'year': 1996, 'tmdbid': 954})


# ---- delete and move ----

import time as _time  # noqa: E402

OLD = int(_time.time()) - 10 * 3600
NEW = int(_time.time()) - 60


def tr_torrent(directory='/dl') -> dict:
    return {HASH: {'id': 7, 'downloadDir': directory, 'files': []}}


def test_transmission_get_maps_hash_and_added() -> None:
    """The listing carries the hash and the add time of each torrent."""
    client = Transmission({'url': 'http://t'})
    client._rpc_request = lambda method, params=None: {'torrents': [
        {'name': 'Film.1996.1080p', 'hashString': HASH, 'addedDate': OLD}]}
    item = client.get()[0]
    assert item['torrent_hash'] == HASH and item['added'] == OLD


@pytest.mark.parametrize('query, expected', [
    (None, ['old', 'new', 'unknown']),
    ('Old', ['old']),
    ({'min_age': 1}, ['old']),
    ({'min_age': 0}, ['old', 'new', 'unknown']),
    ({'min_age': 'x'}, ['old', 'new', 'unknown']),
    ({'min_age': 100}, []),
])
def test_get_query_min_age(query, expected) -> None:
    """min_age keeps the torrents added long enough ago; an unknown add time never qualifies."""
    client = Transmission({'url': 'http://t'})
    rows = [{'name': 'Old.1996.1080p', 'addedDate': OLD}, {'name': 'New.1996.1080p', 'addedDate': NEW},
            {'name': 'Unknown.1996.1080p'}]
    client._rpc_request = lambda method, params=None: {'torrents': rows}
    names = [item['title'].lower() for item in client.get(query=query)]
    assert names == expected


def test_transmission_delete() -> None:
    """The torrent is removed, its files only on request; unknown torrents stay."""
    client = transmission(tr_torrent())
    data = [added(), added(torrent_hash=None, link=''), added(torrent_hash='f' * 40)]
    client.delete(data)
    assert ('torrent-remove', {'ids': [7], 'delete-local-data': False}) in client.calls
    assert [item['transmission_deleted'] for item in data] == ['deleted', 'missing', 'missing']
    client._cfg = {'delete_files': True}
    client.delete([added()])
    assert client.calls[-1] == ('torrent-remove', {'ids': [7], 'delete-local-data': True})
    client._remove_torrent = Mock(return_value=False)
    data = [added()]
    client.delete(data)
    assert data[0]['transmission_deleted'] == 'error'
    assert client.delete(None) is None


def test_transmission_move() -> None:
    """The torrent data moves; a torrent already there is done; no location does nothing."""
    client = transmission(tr_torrent())
    client._cfg = {'location': '/archive'}
    data = [added()]
    client.move(data)
    assert data[0]['transmission_moved'] == 'moved'
    assert client.calls[-1] == ('torrent-set-location', {'ids': [7], 'location': '/archive', 'move': True})
    client._cfg = {'location': '/dl/'}
    data = [added()]
    client.move(data)
    assert data[0]['transmission_moved'] == 'done'
    client._cfg = {}
    data = [added()]
    client.move(data)
    assert 'transmission_moved' not in data[0]
    client._cfg = {'location': '/a'}
    client._move_content = Mock(return_value=False)
    data = [added()]
    client.move(data)
    assert data[0]['transmission_moved'] == 'error'


def test_qbittorrent_delete_and_move() -> None:
    """qBittorrent removes and moves through its WebAPI."""
    client = qbittorrent([{'save_path': '/dl'}], [])
    client._cfg = {'delete_files': True}
    data = [queued()]
    client.delete(data)
    assert data[0]['qbittorrent_deleted'] == 'deleted'
    assert client.posts[-1] == ('api/v2/torrents/delete', {'hashes': HASH, 'deleteFiles': 'true'})
    client._cfg = {'location': '/archive'}
    data = [queued()]
    client.move(data)
    assert data[0]['qbittorrent_moved'] == 'moved'
    assert client.posts[-1] == ('api/v2/torrents/setLocation', {'hashes': HASH, 'location': '/archive'})
    failing = qbittorrent([{'save_path': '/dl'}], [], status=500)
    data = [queued()]
    failing.delete(data)
    assert data[0]['qbittorrent_deleted'] == 'error'
