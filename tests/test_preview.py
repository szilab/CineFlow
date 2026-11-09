"""Flow test runs: real reads, skipped side effects, previews."""

import json
import threading
from pathlib import Path

import pytest
import yaml

from cineflow.core import preview, store
from cineflow.web.api import Api

ITEMS = [
    {'title': 'A', 'year': '2020', 'tmdbid': 1, 'link': 'https://j/dl?apikey=SECRET1&x=1', 'long': 'x' * 400},
    {'title': 'A', 'year': '2020', 'tmdbid': 1},
    {'title': 'B', 'year': '2021', 'nested': {'k': [1, 2]}},
]


@pytest.fixture
def debug_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr('cineflow.internal.tools.debug_directory', lambda: tmp_path / 'debug')
    path = tmp_path / 'debug' / 'exported_data.json'
    path.parent.mkdir()
    path.write_text(json.dumps(ITEMS))
    return path


def flow(*steps) -> dict:
    return {'name': 'Test', 'enabled': False, 'steps': list(steps)}


LOAD = {'name': 'load', 'module': 'tools', 'action': 'data_import'}
DEDUPE = {'name': 'dedupe', 'module': 'tools', 'action': 'remove_duplicates', 'input': 'previous'}


def test_test_run_previews_and_skips_side_effects(debug_file: Path, tmp_path: Path) -> None:
    exported = tmp_path / 'debug' / 'out.json'
    result = preview.run_test(flow(
        LOAD, DEDUPE,
        {'name': 'export', 'module': 'tools', 'action': 'data_export',
         'input': {'data': 'previous', 'filename': 'out.json'}},
        {'name': 'after', 'module': 'tools', 'action': 'remove_duplicates', 'input': '{{export}}'},
    ))

    assert result['status'] == 'success'
    statuses = [(step['name'], step['status'], step['count']) for step in result['steps']]
    assert statuses == [('load', 'ok', 3), ('dedupe', 'ok', 2), ('export', 'skipped', 2), ('after', 'ok', 2)]
    assert not exported.exists()
    first = result['steps'][0]['items'][0]
    assert 'SECRET1' not in first['link'] and first['long'].endswith('…') and len(first['long']) < 310
    assert result['steps'][0]['items'][2]['nested'] == {'k': [1, 2]}
    assert isinstance(result['logs'], list)


def test_test_run_of_both_kinds_reports_each_pass(debug_file: Path) -> None:
    result = preview.run_test({**flow(LOAD, DEDUPE), 'kind': 'both'})

    assert result['status'] == 'success'
    assert [(step['name'], step['kind'], step['count']) for step in result['steps']] == [
        ('load', 'movie', 3), ('dedupe', 'movie', 2), ('load', 'tv', 3), ('dedupe', 'tv', 2)]
    assert preview.run_test(flow(LOAD))['steps'][0]['kind'] is None


def test_test_run_stops_at_until_and_on_failures(debug_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert [step['name'] for step in preview.FlowTest(flow(LOAD, DEDUPE), until=0).flow.steps] == ['load', 'dedupe']
    test = preview.FlowTest(flow(LOAD, DEDUPE), until=0)
    test.run()
    assert [step['name'] for step in test.steps] == ['load'] and test.status == 'success'

    result = preview.run_test(flow(LOAD, {'name': 'x', 'module': 'tools', 'action': 'missing'}))
    assert result['status'] == 'failed' and result['steps'][-1]['message'] == 'Action not found.'

    result = preview.run_test(flow({'name': 'x', 'module': 'nope', 'action': 'get'}))
    assert result['steps'][-1]['message'] == 'Module could not be loaded.'

    class Broken:
        def __init__(self, config):
            pass

        def get(self):
            return None

        def boom(self):
            raise RuntimeError('kaput')

    monkeypatch.setattr('cineflow.core.runner.load_module', lambda name: Broken)
    result = preview.run_test(flow({'name': 'g', 'module': 'fake', 'action': 'get'}))
    assert result['status'] == 'failed' and 'Retrieval failed' in result['steps'][0]['message']
    result = preview.run_test(flow({'name': 'b', 'module': 'fake', 'action': 'boom'}))
    assert result['steps'][0] == {**result['steps'][0], 'status': 'failed', 'message': 'kaput'}
    assert preview.run_test({'name': 'empty', 'steps': []})['status'] == 'failed'


def test_test_run_timeout_and_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    gate = threading.Event()

    class Slow:
        def __init__(self, config):
            pass

        def get(self):
            gate.wait(5)
            return []

    monkeypatch.setattr('cineflow.core.runner.load_module', lambda name: Slow)
    slow = flow({'name': 's', 'module': 'fake', 'action': 'get'}, {'name': 't', 'module': 'fake', 'action': 'get'})
    assert preview.run_test(slow, timeout=0.05)['status'] == 'timeout'
    gate.set()

    monkeypatch.setattr(preview, '_running', threading.BoundedSemaphore(1))
    preview._running.acquire()
    try:
        assert preview.run_test(slow) is None
    finally:
        preview._running.release()


def test_preview_output_shapes() -> None:
    assert preview.preview_output(None) == {'count': None, 'items': []}
    assert preview.preview_output({'a': 1}) == {'count': 1, 'items': [{'a': 1}]}
    assert preview.preview_output('text') == {'count': 1, 'items': [{'value': 'text'}]}
    assert preview.preview_output(['x'])['items'] == [{'value': 'x'}]
    assert len(preview.preview_output([{}] * 40)['items']) == preview.PREVIEW_ITEMS


def test_test_run_api(debug_file: Path, isolated_config_directory: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = Api()
    status, payload = api.handle('POST', '/api/flows/test', {'flow': flow(LOAD, DEDUPE), 'until': 0})
    assert status == 200 and [step['name'] for step in payload['steps']] == ['load']

    broken = flow(LOAD, {'name': 'x', 'module': 'nope', 'action': 'get'})
    assert api.handle('POST', '/api/flows/test', {'flow': broken, 'until': 0})[0] == 200
    status, payload = api.handle('POST', '/api/flows/test', {'flow': broken})
    assert status == 422 and payload['error']['issues'][0]['code'] == 'unknown_module'
    for until in (-1, 'x', True):
        assert api.handle('POST', '/api/flows/test', {'flow': broken, 'until': until})[0] == 400
    assert api.handle('POST', '/api/flows/test', {'flow': []})[0] == 400

    isolated_config_directory.mkdir(parents=True, exist_ok=True)
    flow_id = store.save_flow({**flow(LOAD), 'steps': [{**LOAD, 'config': {'token': 'stored'}}]})
    seen = {}
    monkeypatch.setattr(preview, 'run_test', lambda definition: seen.update(definition) or None)
    unsaved = yaml.safe_load(yaml.safe_dump(flow(LOAD)))
    status, _ = api.handle('POST', '/api/flows/test', {'flow': unsaved, 'id': flow_id})
    assert status == 429
    assert seen['steps'][0]['config'] == {'token': 'stored'} and seen['enabled'] is True


def test_step_results_can_be_paged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr('cineflow.internal.tools.debug_directory', lambda: tmp_path)
    (tmp_path / 'exported_data.json').write_text(json.dumps(
        [{'title': f'T{n}', 'year': '2020', 'tmdbid': n} for n in range(60)]))
    result = preview.run_test(flow(LOAD))
    step = result['steps'][0]

    assert result['page_size'] == preview.PREVIEW_ITEMS and len(result['id']) == 32
    assert (step['count'], step['kept'], len(step['items'])) == (60, 60, preview.PREVIEW_ITEMS)
    last = preview.result_page(result['id'], 0, 2)
    assert last['pages'] == 3 and [item['title'] for item in last['items']] == [f'T{n}' for n in range(50, 60)]
    assert preview.result_page(result['id'], 0, 3) is None
    assert preview.result_page(result['id'], 1, 0) is None
    assert preview.result_page('0' * 32, 0, 0) is None

    api = Api()
    page = api.handle('GET', f"/api/flows/test/{result['id']}/0/1")[1]
    assert page['page'] == 1 and page['items'][0]['title'] == 'T25'
    assert api.handle('GET', f"/api/flows/test/{'0' * 32}/0/0")[0] == 404


def test_only_recent_tests_are_kept_for_paging(debug_file: Path) -> None:
    ids = [preview.run_test(flow(LOAD))['id'] for _ in range(preview.KEPT_TESTS + 1)]

    assert preview.result_page(ids[0], 0, 0) is None
    assert preview.result_page(ids[-1], 0, 0)['count'] == 3
