"""Flow runtime additions: instances, structured references, status, manual runs."""

import threading
from pathlib import Path

import pytest
import yaml

from cineflow.core import runner
from cineflow.core.config import Config
from cineflow.core.logger import recent_logs


class Recorder:
    """In-memory module recording its configuration and calls."""

    configs: list[dict] = []
    calls: list[tuple] = []
    gate: threading.Event | None = None
    entered: threading.Event | None = None

    def __init__(self, config: dict) -> None:
        self.config = config
        self.configs.append(config)

    def get(self) -> list:
        if self.entered is not None:
            self.entered.set()
        if self.gate is not None:
            self.gate.wait(timeout=5)
        self.calls.append(('get',))
        return [{'title': 'A', 'year': 2020}]

    def other(self) -> list:
        self.calls.append(('other',))
        return [{'title': 'B', 'year': 2021}]

    def collect(self, data=None, query=None) -> list:
        self.calls.append(('collect', data, query))
        return data

    def boom(self) -> None:
        raise RuntimeError('broken')


@pytest.fixture
def make_flow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(runner, 'load_module', lambda name: Recorder)
    Recorder.configs, Recorder.calls, Recorder.gate, Recorder.entered = [], [], None, None

    def create(steps: list[dict], name: str = 'Test flow') -> runner.Flow:
        file = tmp_path / 'flow.yaml'
        file.write_text(yaml.safe_dump({'name': name, 'steps': steps}), encoding='utf-8')
        flow = runner.Flow(str(file))
        flow._first_run = False
        return flow

    return create


def test_step_instance_settings_are_merged_under_step_settings(make_flow, isolated_config_directory) -> None:
    Config().set('instances', {'home': {'module': 'fake', 'name': 'Home', 'config': {'url': 'u', 'limit': 5}}})
    flow = make_flow([{'name': 's', 'module': 'fake', 'instance': 'home', 'action': 'get', 'config': {'limit': 9}}])

    assert flow.execute() == 'success'
    assert Recorder.configs == [{'url': 'u', 'limit': 9, 'kind': 'movie'}]


@pytest.mark.parametrize('instance', ['missing', 'other'])
def test_unknown_or_foreign_instance_fails_the_flow(make_flow, instance: str) -> None:
    Config().set('instances', {'other': {'module': 'different', 'config': {}}})
    flow = make_flow([{'name': 's', 'module': 'fake', 'instance': instance, 'action': 'get'}])

    assert flow.execute() == 'failed'
    assert Recorder.calls == []
    assert 'could not be loaded' in flow.state['last_error']


def test_structured_input_resolves_named_and_merged_references(make_flow) -> None:
    flow = make_flow([
        {'name': 'first', 'module': 'fake', 'action': 'get'},
        {'name': 'second', 'module': 'fake', 'action': 'other'},
        {'name': 'named', 'module': 'fake', 'action': 'collect',
         'input': {'data': '{{first}}', 'query': {'q': 1}}},
        {'name': 'merged', 'module': 'fake', 'action': 'collect',
         'input': {'data': ['first', '{{second}}']}},
    ])

    flow.execute()

    assert Recorder.calls[2] == ('collect', [{'title': 'A', 'year': 2020}], {'q': 1})
    assert Recorder.calls[3] == ('collect', [{'title': 'A', 'year': 2020}, {'title': 'B', 'year': 2021}], None)


def test_execute_records_status_and_attributes_logs(make_flow) -> None:
    flow = make_flow([{'name': 'bad', 'module': 'fake', 'action': 'boom'}], name='Logged flow')

    assert flow.execute() == 'failed'

    assert flow.state['last_status'] == 'failed'
    assert flow.state['last_step'] == 'bad'
    assert 'broken' in flow.state['last_error']
    assert flow.state['running'] is False and flow.state['last_end'] >= flow.state['last_start']
    assert any('broken' in record['message'] for record in recent_logs(flow='Logged flow'))


def test_disabled_flow_runs_only_when_forced(make_flow, tmp_path: Path) -> None:
    file = tmp_path / 'flow.yaml'
    file.write_text(yaml.safe_dump({'enabled': False, 'steps': [{'module': 'fake', 'action': 'get'}]}))
    flow = runner.Flow(str(file))

    assert flow.execute() is None
    assert flow.execute(force=True) == 'success'


def test_trigger_runs_in_background_and_refuses_overlap(make_flow) -> None:
    flow = make_flow([{'name': 's', 'module': 'fake', 'action': 'get'}])
    Recorder.gate, Recorder.entered = threading.Event(), threading.Event()

    assert flow.trigger() is True
    assert Recorder.entered.wait(timeout=5)
    assert flow.running
    assert flow.trigger() is False
    assert flow.execute() is None
    Recorder.gate.set()
    for _ in range(200):
        if not flow.running and flow.state['last_status']:
            break
        threading.Event().wait(0.01)
    assert flow.state['last_status'] == 'success'


def test_invalid_flow_cannot_be_triggered(tmp_path: Path) -> None:
    file = tmp_path / 'flow.yaml'
    file.write_text('steps: []')
    assert runner.Flow(str(file)).trigger() is False


def test_reset_modules_rebuilds_instances(make_flow) -> None:
    flow = make_flow([{'name': 's', 'module': 'fake', 'action': 'get'}])
    flow.execute()
    flow.execute()
    assert len(Recorder.configs) == 1

    flow.reset_modules()
    flow.execute()

    assert len(Recorder.configs) == 2


def test_manager_refresh_and_status_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv('CFG_DIRECTORY', str(tmp_path))
    monkeypatch.setattr(runner.FlowManager, 'start', lambda self: None)
    monkeypatch.setattr(runner, 'cfg', lambda *args, **kwargs: 'sequential')
    manager = runner.FlowManager()
    file = tmp_path / 'one.yaml'
    file.write_text(yaml.safe_dump({'name': 'One', 'steps': [{'module': 'tools', 'action': 'remove_duplicates'}]}))

    manager.refresh()

    flow = manager.flows()[str(file)]
    assert flow.name == 'One'
    assert manager.execution_mode == 'sequential'
    assert manager.next_due(str(file)) is not None
    assert manager.next_due('missing') is None
    flow._mod_cache = {'x': object()}
    manager.reset_modules()
    assert flow._mod_cache == {}


def test_manager_logs_validation_findings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    messages = []
    monkeypatch.setattr(runner, 'log', lambda message, level='DEBUG': messages.append((level, message)))
    file = tmp_path / 'bad.yaml'
    file.write_text(yaml.safe_dump({'name': 'Bad', 'steps': [{'module': 'nope', 'action': 'get'}]}))

    runner.FlowManager._report_issues(str(file))

    assert any(level == 'WARNING' and "Unknown module 'nope'" in message for level, message in messages)
    file.write_text(': not yaml : [')
    runner.FlowManager._report_issues(str(file))
    assert messages[-1][0] == 'DEBUG'


def test_stop_waits_for_a_manual_run(make_flow) -> None:
    flow = make_flow([{'name': 's', 'module': 'fake', 'action': 'get'}])
    Recorder.gate, Recorder.entered = threading.Event(), threading.Event()
    assert flow.trigger()
    assert Recorder.entered.wait(timeout=5)

    assert flow.stop(timeout=0.05) is False
    Recorder.gate.set()
    assert flow.stop(timeout=5) is True
