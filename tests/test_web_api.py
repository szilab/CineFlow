"""Web API, file store and HTTP server behavior without external services."""

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from cineflow.core import store
from cineflow.core.config import Config
from cineflow.web import api as api_module
from cineflow.web.api import Api
from cineflow.web.server import WebServer

VALID_FLOW = {
    'name': 'Trending',
    'enabled': True,
    'delay': 30,
    'steps': [
        {'name': 'collect', 'module': 'tmdb', 'action': 'get'},
        {'name': 'dedupe', 'module': 'tools', 'action': 'remove_duplicates', 'input': 'previous'},
    ],
}


@pytest.fixture
def config_dir(isolated_config_directory: Path) -> Path:
    isolated_config_directory.mkdir(parents=True, exist_ok=True)
    (isolated_config_directory / 'config.yaml').write_text(yaml.safe_dump({
        'tmdb': {'token': 'secret-token', 'language': 'hu-HU'},
        'jellyfin': {'url': 'http://jf', 'token': 'jf-token'},
    }))
    return isolated_config_directory


class FakeFlow:
    def __init__(self, name: str, valid: bool = True, running: bool = False) -> None:
        self.name = name
        self.valid = valid
        self.running = running
        self.triggered = 0
        self.state = {'last_status': 'success', 'last_start': 1.0}

    def trigger(self) -> bool:
        self.triggered += 1
        return not self.running


class FakeManager:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.loaded = {}
        self.refreshed = 0
        self.resets = 0
        self.execution_mode = 'parallel'

    def refresh(self) -> None:
        self.refreshed += 1

    def flows(self) -> dict:
        return self.loaded

    def next_due(self, file: str):
        return None

    def reset_modules(self) -> None:
        self.resets += 1


@pytest.fixture
def manager(config_dir: Path) -> FakeManager:
    return FakeManager(config_dir)


@pytest.fixture
def api(manager: FakeManager) -> Api:
    return Api(flow_manager=manager)


def ok(result: tuple[int, dict], status: int = 200) -> dict:
    assert result[0] == status, result
    return result[1]


# ------------------------------------------------------------------ routing

def test_routing_errors(api: Api) -> None:
    assert api.handle('GET', '/api/nothing')[0] == 404
    assert api.handle('PATCH', '/api/flows')[0] == 405
    assert ok(api.handle('GET', '/api/health/'))['status'] == 'ok'
    assert api.handle('POST', '/api/instances', 'not json object')[0] == 400


def test_internal_errors_are_not_leaked(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_module.catalog, 'definitions', lambda: 1 / 0)
    status, payload = api.handle('GET', '/api/catalog')
    assert status == 500 and 'division' not in payload['error']['message']


def test_catalog_lists_all_modules(api: Api) -> None:
    modules = ok(api.handle('GET', '/api/catalog'))['modules']
    assert {item['id'] for item in modules} >= {'tmdb', 'jackett', 'library', 'tools'}


def test_catalog_describes_flow_settings_and_export_root(
    api: Api, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv('EXPORT_DIRECTORY', str(tmp_path))
    payload = ok(api.handle('GET', '/api/catalog'))
    settings = {item['key']: item for item in payload['flow_settings']}

    assert payload['export_directory'] == str(tmp_path.resolve())
    assert settings['library_directory']['modules'] == ['library']
    assert settings['library_directory']['kind_default'] is True
    assert settings['search_preference']['modules'] == ['jackett', 'library']
    assert settings['search_preference']['field']['type'] == 'list'


# ---------------------------------------------------------------- instances

def test_instances_mask_secrets_and_report_status(api: Api) -> None:
    instances = {item['id']: item for item in ok(api.handle('GET', '/api/instances'))['instances']}

    assert 'tools' not in instances
    assert instances['tmdb']['config'] == {'language': 'hu-HU'}
    assert instances['tmdb']['secrets'] == ['token']
    assert instances['tmdb']['status'] == 'valid'
    assert instances['jackett']['status'] == 'incomplete'
    assert 'secret-token' not in json.dumps(instances)
    assert api.handle('GET', '/api/instances/ghost')[0] == 404


def test_update_default_keeps_unsent_secret_and_clears_empty_one(api: Api, manager: FakeManager) -> None:
    result = ok(api.handle('PUT', '/api/instances/tmdb', {'config': {'language': 'en-US'}}))
    assert result['status'] == 'valid'
    assert Config().data()['tmdb'] == {'language': 'en-US', 'token': 'secret-token'}
    assert manager.resets == 1

    result = ok(api.handle('PUT', '/api/instances/tmdb', {'config': {'token': ''}}))
    assert result['status'] == 'incomplete'
    assert 'token' not in Config().data()['tmdb']


def test_invalid_settings_are_not_saved(api: Api) -> None:
    status, payload = api.handle('PUT', '/api/instances/jellyfin', {'config': {'url': 'not-a-url'}})

    assert status == 422
    assert payload['error']['issues'][0]['path'] == ['jellyfin', 'url']
    assert Config().data()['jellyfin']['url'] == 'http://jf'
    assert api.handle('PUT', '/api/instances/jellyfin', {})[0] == 400
    assert api.handle('PUT', '/api/instances/jellyfin', {'config': []})[0] == 400


def test_named_instance_lifecycle(api: Api, config_dir: Path) -> None:
    created = ok(api.handle('POST', '/api/instances', {'module': 'jellyfin', 'name': 'Home Jellyfin'}), 201)
    assert created['id'] == 'home-jellyfin' and created['status'] == 'valid'  # inherits the default
    second = ok(api.handle('POST', '/api/instances', {'module': 'jellyfin', 'name': 'Home Jellyfin'}), 201)
    assert second['id'] == 'home-jellyfin-2'
    assert api.handle('POST', '/api/instances', {'module': 'jellyfin', 'name': 'X', 'id': 'jellyfin'})[0] == 400
    assert api.handle('POST', '/api/instances', {'module': 'nope', 'name': 'X'})[0] == 400
    assert api.handle('POST', '/api/instances', {'module': 'plex', 'name': ' '})[0] == 400
    assert api.handle('POST', '/api/instances', {'module': 'plex', 'name': 'P', 'config': []})[0] == 400

    updated = ok(api.handle('PUT', '/api/instances/home-jellyfin', {
        'name': 'Living room', 'config': {'url': 'http://living:8096', 'token': 'own'},
    }))
    assert updated['name'] == 'Living room' and updated['secrets'] == ['token']
    assert Config().data()['instances']['home-jellyfin']['config']['token'] == 'own'

    store.save_flow({'name': 'Uses', 'enabled': False, 'steps': [
        {'name': 's', 'module': 'jellyfin', 'instance': 'home-jellyfin', 'action': 'get'}]})
    status, payload = api.handle('DELETE', '/api/instances/home-jellyfin')
    assert status == 409 and 'uses' in payload['error']['message']
    assert api.handle('DELETE', '/api/instances/jellyfin')[0] == 400
    assert api.handle('DELETE', '/api/instances/ghost')[0] == 404
    assert ok(api.handle('DELETE', '/api/instances/home-jellyfin-2')) == {'deleted': 'home-jellyfin-2'}


def test_validate_unsaved_instance_settings(api: Api) -> None:
    ok(api.handle('POST', '/api/instances', {'module': 'plex', 'name': 'Plex'}), 201)
    result = ok(api.handle('POST', '/api/instances/plex-2/validate', {'config': {'url': 'bad'}}))
    assert result['status'] == 'invalid'
    assert ok(api.handle('POST', '/api/instances/plex-2/validate'))['status'] == 'incomplete'

    result = ok(api.handle('POST', '/api/instances/plex/validate', {'config': {'url': 'http://p', 'token': 't'}}))
    assert result == {'status': 'valid', 'issues': []}
    assert Config().data().get('plex') is None


def test_connection_test_uses_unsaved_settings(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    seen = {}

    from cineflow.integrations.jellyfin import Jellyfin

    class FakeJellyfin:
        DEFINITION = Jellyfin.DEFINITION

        def __init__(self, config):
            seen.update(config)

        def check_connection(self):
            return {'ok': True, 'message': 'Connected'}

    monkeypatch.setattr(api_module.catalog, 'module_class', lambda module_id: FakeJellyfin)
    result = ok(api.handle('POST', '/api/instances/jellyfin/test', {'config': {'url': 'http://new'}}))

    assert result['ok'] is True
    assert seen == {'url': 'http://new', 'token': 'jf-token'}
    instances = {item['id']: item for item in ok(api.handle('GET', '/api/instances'))['instances']}
    assert instances['jellyfin']['test'] == {'ok': True, 'message': 'Connected'}


def test_dropdown_choices_come_from_the_instance_service(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    from cineflow.integrations.jellyfin import Jellyfin

    calls = []

    class FakeJellyfin:
        DEFINITION = Jellyfin.DEFINITION

        def __init__(self, config):
            self.config = config

        def field_choices(self, source):
            calls.append((self.config['url'], source))
            return {'libraries': ['Anime', 'Movies'], 'users': ['adam']}.get(source)

    monkeypatch.setattr(api_module.catalog, 'module_class', lambda module_id: FakeJellyfin)

    assert ok(api.handle('GET', '/api/instances/jellyfin/choices/libraries')) == {'choices': ['Anime', 'Movies']}
    assert ok(api.handle('GET', '/api/instances/jellyfin/choices/users')) == {'choices': ['adam']}
    # reused for a while, read again after the settings change
    ok(api.handle('GET', '/api/instances/jellyfin/choices/libraries'))
    assert calls == [('http://jf', 'libraries'), ('http://jf', 'users')]
    ok(api.handle('PUT', '/api/instances/jellyfin', {'config': {'url': 'http://other'}}))
    ok(api.handle('GET', '/api/instances/jellyfin/choices/libraries'))
    assert calls[-1] == ('http://other', 'libraries')


def test_dropdown_choices_failures(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    # unknown list, list of another module, not set up, unknown instance
    assert api.handle('GET', '/api/instances/jellyfin/choices/nothing')[0] == 404
    assert api.handle('GET', '/api/instances/tmdb/choices/libraries')[0] == 404
    assert api.handle('GET', '/api/instances/plex/choices/libraries')[0] == 409
    assert api.handle('GET', '/api/instances/ghost/choices/libraries')[0] == 404

    from cineflow.integrations.jellyfin import Jellyfin

    class Broken:
        DEFINITION = Jellyfin.DEFINITION

        def __init__(self, config):
            pass

        def field_choices(self, source):
            raise ValueError('Failed to query Jellyfin libraries: HTTP 500')

    monkeypatch.setattr(api_module.catalog, 'module_class', lambda module_id: Broken)
    status, payload = api.handle('GET', '/api/instances/jellyfin/choices/libraries')
    assert status == 502 and 'HTTP 500' in payload['error']['message']

    class Silent(Broken):
        def field_choices(self, source):
            return None

    monkeypatch.setattr(api_module.catalog, 'module_class', lambda module_id: Silent)
    assert api.handle('GET', '/api/instances/jellyfin/choices/users')[0] == 404


def test_library_fields_declare_dropdown_choices(api: Api) -> None:
    modules = {item['id']: item for item in ok(api.handle('GET', '/api/catalog'))['modules']}
    query = {spec['key']: spec['choices'] for spec in modules['jellyfin']['actions'][0]['query']}

    assert query['parentLibrary'] == 'libraries' and query['userName'] == 'users'
    assert query['isFavorite'] == ''
    # one User dropdown: its "All" entry writes allUsers, which has no field of its own
    specs = {spec['key']: spec for spec in modules['jellyfin']['actions'][0]['query']}
    assert specs['userName']['all_key'] == 'allUsers' and specs['allUsers']['hidden'] is True
    # one Libraries choice: All / Only / All except, with one or more libraries
    library = next(spec for spec in modules['jellyfin']['actions'][2]['query'] if spec['key'] == 'parentLibrary')
    inverse = next(spec for spec in modules['jellyfin']['actions'][2]['query'] if spec['key'] == 'isInverse')
    assert library['multiple'] is True and library['inverse_key'] == 'isInverse' and inverse['hidden'] is True


def test_connection_test_failures(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    assert api.handle('POST', '/api/instances/library/test')[0] == 400
    assert ok(api.handle('POST', '/api/instances/plex/test'))['ok'] is False

    from cineflow.integrations.jellyfin import Jellyfin

    class Broken:
        DEFINITION = Jellyfin.DEFINITION

        def __init__(self, config):
            raise ValueError('cannot connect')

    monkeypatch.setattr(api_module.catalog, 'module_class', lambda module_id: Broken)
    assert ok(api.handle('POST', '/api/instances/jellyfin/test')) == {'ok': False, 'message': 'cannot connect'}


# --------------------------------------------------------------------- flows

def test_flow_create_read_update_delete(api: Api, manager: FakeManager, config_dir: Path) -> None:
    created = ok(api.handle('POST', '/api/flows', {'flow': VALID_FLOW}), 201)
    flow_id = created['id']
    assert flow_id == 'trending' and manager.refreshed == 1
    assert (config_dir / 'trending.yaml').is_file()

    data = ok(api.handle('GET', f'/api/flows/{flow_id}'))
    assert data['flow']['version'] == 1 and data['issues'] == []
    assert data['runtime'] == {'loaded': False, 'mode': 'parallel'}

    changed = {**data['flow'], 'delay': 45}
    updated = ok(api.handle('PUT', f'/api/flows/{flow_id}', {'flow': changed, 'revision': data['revision']}))
    assert updated['revision'] != data['revision']
    assert store.read_flow(flow_id)['version'] == 2

    stale = api.handle('PUT', f'/api/flows/{flow_id}', {'flow': changed, 'revision': data['revision']})
    assert stale[0] == 409

    summary = ok(api.handle('GET', '/api/flows'))['flows'][0]
    assert summary['name'] == 'Trending' and summary['delay'] == 45 and summary['status'] == 'valid'

    assert ok(api.handle('DELETE', f'/api/flows/{flow_id}')) == {'deleted': flow_id}
    assert api.handle('GET', f'/api/flows/{flow_id}')[0] == 404
    assert list((config_dir / '.backups').glob('trending.yaml.*.bak'))


def test_flows_with_errors_can_only_be_saved_disabled(api: Api) -> None:
    broken = {'name': 'Broken', 'steps': [{'name': 'x', 'module': 'nope', 'action': 'get'}]}

    status, payload = api.handle('POST', '/api/flows', {'flow': broken})
    assert status == 422 and payload['error']['issues'][0]['code'] == 'unknown_module'

    created = ok(api.handle('POST', '/api/flows', {'flow': {**broken, 'enabled': False}}), 201)
    assert created['issues'][0]['code'] == 'unknown_module'
    assert api.handle('POST', '/api/flows', {'flow': {'name': 'x', 'enabled': False, 'steps': 'x'}})[0] == 422
    assert api.handle('POST', '/api/flows', {'flow': []})[0] == 400
    assert api.handle('PUT', '/api/flows/broken', {'flow': []})[0] == 400


def test_flow_step_secrets_are_masked_and_restored(api: Api) -> None:
    step = {'name': 'collect', 'module': 'tmdb', 'action': 'get', 'config': {'token': 'step-secret'}}
    flow = {**VALID_FLOW, 'steps': [step]}
    flow_id = ok(api.handle('POST', '/api/flows', {'flow': flow}), 201)['id']

    data = ok(api.handle('GET', f'/api/flows/{flow_id}'))
    assert data['flow']['steps'][0]['config'] == {}
    assert data['secrets'] == {0: ['token']}
    exported = ok(api.handle('GET', f'/api/flows/{flow_id}/yaml'))
    assert 'step-secret' not in exported['yaml'] and exported['filename'] == f'{flow_id}.yaml'

    ok(api.handle('PUT', f'/api/flows/{flow_id}', {'flow': data['flow']}))
    assert store.read_flow(flow_id)['steps'][0]['config']['token'] == 'step-secret'


def test_validate_import_and_export(api: Api) -> None:
    result = ok(api.handle('POST', '/api/flows/validate', {'flow': VALID_FLOW}))
    assert result == {'valid': True, 'issues': []}

    text = yaml.safe_dump(VALID_FLOW)
    imported = ok(api.handle('POST', '/api/flows/import', {'yaml': text}), 201)
    assert imported['enabled'] is True and store.read_flow(imported['id'])['name'] == 'Trending'

    bad = yaml.safe_dump({'name': 'Bad', 'steps': [{'module': 'nope', 'action': 'x'}]})
    assert api.handle('POST', '/api/flows/import', {'yaml': bad})[0] == 422
    draft = ok(api.handle('POST', '/api/flows/import', {'yaml': bad, 'as_draft': True}), 201)
    assert draft['enabled'] is False and store.read_flow(draft['id'])['enabled'] is False
    assert api.handle('POST', '/api/flows/import', {'yaml': ': ['})[0] == 400
    assert api.handle('POST', '/api/flows/import', {'yaml': '- a list'})[0] == 400
    assert api.handle('POST', '/api/flows/import', {'yaml': 5})[0] == 400


def test_run_and_runtime_state(api: Api, manager: FakeManager, config_dir: Path) -> None:
    flow_id = ok(api.handle('POST', '/api/flows', {'flow': VALID_FLOW}), 201)['id']
    assert api.handle('POST', f'/api/flows/{flow_id}/run')[0] == 404

    fake = FakeFlow('Trending')
    manager.loaded = {str(config_dir / f'{flow_id}.yaml'): fake}
    assert ok(api.handle('POST', f'/api/flows/{flow_id}/run'), 202) == {'started': flow_id}
    assert fake.triggered == 1
    runtime = ok(api.handle('GET', f'/api/flows/{flow_id}'))['runtime']
    assert runtime['last_status'] == 'success' and runtime['loaded'] is True

    fake.running = True
    assert api.handle('POST', f'/api/flows/{flow_id}/run')[0] == 409
    fake.valid = False
    assert api.handle('POST', f'/api/flows/{flow_id}/run')[0] == 409
    assert api.handle('POST', '/api/flows/missing/run')[0] == 404
    assert Api().handle('POST', f'/api/flows/{flow_id}/run')[0] == 503


def test_flow_logs_settings_validation_and_config_export(api: Api, manager: FakeManager, config_dir: Path) -> None:
    flow_id = ok(api.handle('POST', '/api/flows', {'flow': VALID_FLOW}), 201)['id']
    (config_dir / 'broken.yaml').write_text(': [')
    from cineflow.core.logger import log, log_context
    with log_context('Trending'):
        log('hello from the flow', level='ERROR')

    logs = ok(api.handle('GET', f'/api/flows/{flow_id}/logs'))['logs']
    assert logs[-1]['message'] == 'hello from the flow'

    settings = ok(api.handle('GET', '/api/settings'))
    assert settings['execution'] == 'parallel' and settings['restart_required'] is False
    settings = ok(api.handle('PUT', '/api/settings', {'execution': 'sequential'}))
    assert settings['restart_required'] is True and Config().data()['execution'] == 'sequential'
    assert api.handle('PUT', '/api/settings', {'execution': 'turbo'})[0] == 422

    report = ok(api.handle('GET', '/api/validate'))
    assert report['flows'][flow_id] == [] and report['flows']['broken'][0]['code'] == 'yaml'
    flows = {item['id']: item for item in ok(api.handle('GET', '/api/flows'))['flows']}
    assert flows['broken']['status'] == 'invalid'

    exported = ok(api.handle('GET', '/api/config/export'))['yaml']
    assert 'secret-token' not in exported and 'jf-token' not in exported and 'hu-HU' in exported


# --------------------------------------------------------------------- store

def test_store_ids_backups_and_masks(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, 'BACKUPS_KEPT', 2)
    flow_id = store.save_flow({'name': 'Config', 'steps': []})
    assert flow_id == 'config-2'
    assert store.new_flow_id('!!!') == 'flow'
    for delay in range(4):
        store.save_flow({'name': 'Config', 'delay': delay, 'steps': []}, flow_id)
    assert len(list((config_dir / '.backups').glob(f'{flow_id}.yaml.*.bak'))) == 2
    with pytest.raises(store.StoreError):
        store.flow_path('../config')
    with pytest.raises(store.StoreError):
        store.flow_path('missing')
    assert store.backup(config_dir / 'nothing.yaml') is None
    assert list(store.flow_yaml({'steps': [{'action': 'a', 'name': 'n', 'x': 1}], 'name': 'F'}).splitlines())[:3] == [
        'name: F', 'steps:', '- name: n']
    assert store.mask(None, 'x') == ({}, [])
    config = store.mask_config({'execution': 'parallel', 'instances': {
        'a': {'module': 'plex', 'name': 'A', 'config': {'token': 't', 'url': 'u'}}, 'b': 'odd'}})
    assert config['instances']['a']['config'] == {'url': 'u'} and config['instances']['b'] == 'odd'


def test_config_replace_writes_atomically_with_backup(config_dir: Path) -> None:
    Config().replace({'execution': 'sequential'})

    assert yaml.safe_load((config_dir / 'config.yaml').read_text()) == {'execution': 'sequential'}
    assert list((config_dir / '.backups').glob('config.yaml.*.bak'))
    with pytest.raises(ValueError):
        Config().replace([])


# -------------------------------------------------------------------- server

def request(port: int, method: str, path: str, body=None, content_type='application/json'):
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=data, method=method)
    if content_type:
        req.add_header('Content-Type', content_type)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def test_http_server_serves_api_and_static_files(config_dir: Path) -> None:
    server = WebServer(port=0, host='127.0.0.1')
    try:
        port = server.port
        status, headers, body = request(port, 'GET', '/')
        assert status == 200 and b'CineFlow' in body and "frame-ancestors" in headers['Content-Security-Policy']
        assert request(port, 'GET', '/static/app.js')[0] == 200
        assert request(port, 'GET', '/static/funnel.js')[0] == 200
        assert request(port, 'GET', '/static/../api.py')[0] == 404
        assert request(port, 'GET', '/static/%2e%2e/api.py')[0] == 404
        assert request(port, 'GET', '/missing.css')[0] == 404
        assert request(port, 'HEAD', '/')[0] == 200
        assert request(port, 'POST', '/')[0] == 405

        status, _, body = request(port, 'GET', '/api/health')
        assert status == 200 and json.loads(body)['runtime'] is False
        assert request(port, 'POST', '/api/flows/validate', {'flow': VALID_FLOW}, 'text/plain')[0] == 415
        assert request(port, 'POST', '/api/flows/validate', b'{bad', 'application/json')[0] == 400
        status, _, body = request(port, 'POST', '/api/flows/validate', {'flow': VALID_FLOW})
        assert status == 200 and json.loads(body)['valid'] is True
        status, _, body = request(port, 'DELETE', '/api/flows/nothing', None)
        assert status == 404
    finally:
        assert server.close() is True


def test_http_server_rejects_large_bodies(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from cineflow.web import server as server_module
    monkeypatch.setattr(server_module, 'MAX_BODY', 10)
    server = WebServer(port=0, host='127.0.0.1')
    try:
        assert request(server.port, 'POST', '/api/flows/validate', {'flow': VALID_FLOW})[0] == 413
    finally:
        server.stop()


def test_main_app_starts_web_server(monkeypatch: pytest.MonkeyPatch, config_dir: Path) -> None:
    from cineflow import main as main_module

    started = {}

    class FakeWeb:
        def __init__(self, port, flow_manager):
            started.update(port=port, manager=flow_manager)

    monkeypatch.setattr('cineflow.web.server.WebServer', FakeWeb)
    monkeypatch.setattr(main_module, 'FlowManager', lambda: 'manager')
    monkeypatch.setattr(main_module, 'Database', lambda: SimpleNamespace())
    monkeypatch.setattr(main_module, 'CleanupScheduler', lambda: SimpleNamespace())
    main_module.MainApp(web_port=0)

    assert started == {'port': 0, 'manager': 'manager'}


def test_web_port_parsing() -> None:
    from cineflow.main import _web_port

    assert _web_port(None) is None and _web_port('') is None and _web_port('8080') == 8080
    with pytest.raises(ValueError):
        _web_port('70000')
    with pytest.raises(ValueError):
        _web_port('abc')


def test_validate_command(config_dir: Path, capsys: pytest.CaptureFixture) -> None:
    from cineflow.main import main

    (config_dir / 'good.yaml').write_text(yaml.safe_dump(VALID_FLOW))
    with pytest.raises(SystemExit) as exit_info:
        main(['validate'])
    assert exit_info.value.code == 0
    assert 'good.yaml: ok' in capsys.readouterr().out

    (config_dir / 'bad.yaml').write_text(yaml.safe_dump({'name': 'Bad', 'steps': [{'module': 'x', 'action': 'y'}]}))
    (config_dir / 'broken.yml').write_text(': [')
    with pytest.raises(SystemExit) as exit_info:
        main(['validate', '--json'])
    assert exit_info.value.code == 1
    report = json.loads(capsys.readouterr().out)
    assert 'unknown_module' in [issue['code'] for issue in report['bad.yaml']]
    assert report['broken.yml'][0]['code'] == 'yaml'

    (config_dir / 'config.yaml').write_text('execution: [')
    with pytest.raises(SystemExit) as exit_info:
        main(['validate'])
    assert exit_info.value.code == 1


def test_validate_command_does_not_create_files(isolated_config_directory: Path) -> None:
    from cineflow.main import validate_command

    assert validate_command() == 0
    assert not isolated_config_directory.exists()


def test_invalid_web_port_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    from cineflow.main import main

    with pytest.raises(SystemExit, match='Invalid web port'):
        main(['--web-port', 'abc'])


def test_concurrent_requests_are_served(config_dir: Path) -> None:
    server = WebServer(port=0, host='127.0.0.1')
    try:
        results = []
        threads = [threading.Thread(target=lambda: results.append(request(server.port, 'GET', '/api/catalog')[0]))
                   for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
        assert results == [200] * 5
    finally:
        server.stop()


def test_test_all_connections_tests_only_complete_ones(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    tested = []

    class Fake:
        def __init__(self, config):
            self.config = config

        def check_connection(self):
            tested.append(self.config.get('url') or self.config.get('token'))
            return {'ok': True, 'message': 'ok'}

    real = api_module.catalog.module_class

    def fake_class(module_id):
        cls = real(module_id)
        return type('Fake', (Fake,), {'DEFINITION': cls.DEFINITION}) if cls else None

    ok(api.handle('POST', '/api/instances', {'module': 'plex', 'name': 'Half', 'config': {'url': 'http://p'}}), 201)
    monkeypatch.setattr(api_module.catalog, 'module_class', fake_class)
    results = ok(api.handle('POST', '/api/instances/test-all'))['results']

    assert set(results) == {'tmdb', 'jellyfin'}
    assert sorted(tested) == ['http://jf', 'secret-token']


def test_settings_set_by_the_environment_are_reported_read_only(
    api: Api, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setenv('EXPORT_DIRECTORY', str(tmp_path / 'share'))
    monkeypatch.setenv('JELLYFIN_TOKEN', 'from-env')
    instances = {item['id']: item for item in ok(api.handle('GET', '/api/instances'))['instances']}

    assert instances['library']['environment'] == {
        'export_directory': {'name': 'EXPORT_DIRECTORY', 'value': str(tmp_path / 'share')}}
    # secrets are never sent, only that the environment sets them
    assert instances['jellyfin']['environment'] == {'token': {'name': 'JELLYFIN_TOKEN', 'value': None}}
    catalog = ok(api.handle('GET', '/api/catalog'))
    assert catalog['export_directory'] == str((tmp_path / 'share').resolve())
    assert catalog['default_export_directory'] == str(tmp_path / 'home' / 'cineflow' / 'library')
