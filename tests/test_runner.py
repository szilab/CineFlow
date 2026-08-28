"""Regression tests for flow lifecycle and execution behavior."""

from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from cineflow.core import runner


class FakeFlow:
    """Flow double that records lifecycle operations without spawning threads."""

    instances: list["FakeFlow"] = []

    def __init__(self, file: str) -> None:
        self.file = file
        self.name = Path(file).stem
        self.priority = 99
        self._valid = "invalid" not in Path(file).read_text(encoding="utf-8")
        self.started = 0
        self.stopped = 0
        self.runs = 0
        self.instances.append(self)

    def start(self) -> None:
        self.started += 1

    def stop(self) -> None:
        self.stopped += 1

    def run(self) -> None:
        self.runs += 1


@pytest.fixture
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> runner.FlowManager:
    """Create a manager with thread creation disabled."""
    FakeFlow.instances = []
    monkeypatch.setenv("CFG_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(runner.FlowManager, "start", lambda self: None)
    monkeypatch.setattr(runner, "Flow", FakeFlow)
    monkeypatch.setattr(runner, "cfg", lambda *args, **kwargs: "parallel")
    return runner.FlowManager()


def test_manager_discovers_new_flow(manager: runner.FlowManager, tmp_path: Path) -> None:
    flow_file = tmp_path / "first.yaml"
    flow_file.write_text("version: one", encoding="utf-8")

    manager.run()

    assert manager._flows[str(flow_file)].started == 1


def test_manager_removes_one_of_multiple_flows(manager: runner.FlowManager, tmp_path: Path) -> None:
    first, second = tmp_path / "first.yaml", tmp_path / "second.yaml"
    first.write_text("one", encoding="utf-8")
    second.write_text("two", encoding="utf-8")
    manager.run()
    removed = manager._flows[str(first)]
    first.unlink()

    manager.run()

    assert removed.stopped == 1
    assert str(first) not in manager._flows
    assert str(second) in manager._flows


def test_manager_removes_final_flow(manager: runner.FlowManager, tmp_path: Path) -> None:
    flow_file = tmp_path / "only.yaml"
    flow_file.write_text("one", encoding="utf-8")
    manager.run()
    removed = manager._flows[str(flow_file)]
    flow_file.unlink()

    manager.run()

    assert removed.stopped == 1
    assert manager._flows == {}


def test_manager_keeps_unchanged_flow(manager: runner.FlowManager, tmp_path: Path) -> None:
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text("version: one", encoding="utf-8")
    manager.run()
    original = manager._flows[str(flow_file)]

    manager.run()

    assert manager._flows[str(flow_file)] is original
    assert len(FakeFlow.instances) == 1


def test_manager_reloads_changed_flow(manager: runner.FlowManager, tmp_path: Path) -> None:
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text("version: one", encoding="utf-8")
    manager.run()
    original = manager._flows[str(flow_file)]
    flow_file.write_text("version: two", encoding="utf-8")

    manager.run()

    replacement = manager._flows[str(flow_file)]
    assert original.stopped == 1
    assert replacement is not original
    assert replacement.started == 1


def test_invalid_modified_flow_replaces_stale_flow(manager: runner.FlowManager, tmp_path: Path) -> None:
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text("valid", encoding="utf-8")
    manager.run()
    original = manager._flows[str(flow_file)]
    flow_file.write_text("invalid", encoding="utf-8")

    manager.run()

    replacement = manager._flows[str(flow_file)]
    assert original.stopped == 1
    assert replacement is not original
    assert replacement.started == 0


def test_invalid_yaml_reload_stops_the_previous_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A YAML parse failure must not leave the prior valid flow running."""
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text(
        yaml.safe_dump({"steps": [{"module": "fake", "action": "get"}]}),
        encoding="utf-8"
    )
    monkeypatch.setenv("CFG_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(runner.FlowManager, "start", lambda self: None)
    monkeypatch.setattr(runner, "cfg", lambda *args, **kwargs: "parallel")
    start, stop = Mock(), Mock()
    monkeypatch.setattr(runner.Flow, "start", start)
    monkeypatch.setattr(runner.Flow, "stop", stop)
    flow_manager = runner.FlowManager()
    flow_manager.run()
    original = flow_manager._flows[str(flow_file)]
    flow_file.write_text("steps: [", encoding="utf-8")

    flow_manager.run()

    replacement = flow_manager._flows[str(flow_file)]
    assert stop.call_count == 1
    assert replacement is not original
    assert replacement._valid is False
    assert start.call_count == 1


@pytest.mark.parametrize(
    ("configured", "expected", "starts"),
    [("parallel", "parallel", 1), ("sequential", "sequential", 0), ("unknown", "parallel", 1)],
)
def test_execution_mode_is_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, configured: str, expected: str, starts: int
) -> None:
    FakeFlow.instances = []
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text("valid", encoding="utf-8")
    monkeypatch.setenv("CFG_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(runner.FlowManager, "start", lambda self: None)
    monkeypatch.setattr(runner, "Flow", FakeFlow)
    monkeypatch.setattr(runner, "cfg", lambda *args, **kwargs: configured)

    flow_manager = runner.FlowManager()
    flow_manager.run()

    flow = flow_manager._flows[str(flow_file)]
    assert flow_manager._exec_mode == expected
    assert flow.started == starts
    assert flow.runs == (1 if expected == "sequential" else 0)


def test_refresh_delay_prefers_correctly_spelled_environment_variable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The corrected refresh variable takes precedence over the legacy typo."""
    monkeypatch.setenv("CFG_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("FM_REFRESH_SEQ", "15")
    monkeypatch.setenv("FM_RERESH_SEQ", "60")
    monkeypatch.setattr(runner.FlowManager, "start", lambda self: None)
    monkeypatch.setattr(runner, "cfg", lambda *args, **kwargs: "parallel")

    assert runner.FlowManager().delay == 15


class ActionModule:
    """Simple in-memory module used to exercise a Flow's action handling."""

    result: object = "result"
    fail = False
    calls: list[tuple[str, object]] = []

    def __init__(self, config: dict) -> None:
        self.config = config

    def get(self) -> object:
        self.calls.append(("get", None))
        if self.fail:
            raise RuntimeError("unexpected failure")
        return self.result

    def follow(self, data: object = None) -> str:
        self.calls.append(("follow", data))
        return "follow-result"


@pytest.fixture
def flow_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Build parsed flows backed by ActionModule instead of integrations."""
    monkeypatch.setattr(runner, "load_module", lambda name: ActionModule)

    def create(steps: list[dict]) -> runner.Flow:
        ActionModule.calls = []
        ActionModule.result = "result"
        ActionModule.fail = False
        file = tmp_path / "flow.yaml"
        file.write_text(yaml.safe_dump({"steps": steps}), encoding="utf-8")
        flow = runner.Flow(str(file))
        flow._first_run = False
        return flow

    return create


def test_action_exception_aborts_iteration_and_allows_later_run(flow_factory) -> None:
    flow = flow_factory([
        {"name": "first", "module": "fake", "action": "get"},
        {"name": "later", "module": "fake", "action": "follow", "input": "previous"},
    ])
    ActionModule.fail = True

    flow.run()

    assert ActionModule.calls == [("get", None)]
    ActionModule.fail = False
    flow.run()
    assert ActionModule.calls[-2:] == [("get", None), ("follow", "result")]


@pytest.mark.parametrize("result", [None, []])
def test_get_failure_only_treats_none_as_failure(flow_factory, result: object) -> None:
    flow = flow_factory([
        {"name": "source", "module": "fake", "action": "get"},
        {"name": "next", "module": "fake", "action": "follow", "input": "previous"},
    ])
    ActionModule.result = result

    flow.run()

    expected = [("get", None)]
    if result == []:
        expected.append(("follow", []))
    assert ActionModule.calls == expected


@pytest.mark.parametrize(
    "input_value",
    ["previous", "{{source}}", ["{{source}}"], {"data": "previous"}],
)
def test_flow_propagates_previous_output(flow_factory, input_value: object) -> None:
    output = []
    flow = flow_factory([
        {"name": "source", "module": "fake", "action": "get"},
        {"name": "next", "module": "fake", "action": "follow", "input": input_value},
    ])
    ActionModule.result = output

    flow.run()

    assert ActionModule.calls[-1] == ("follow", output if input_value != ["{{source}}"] else [])
