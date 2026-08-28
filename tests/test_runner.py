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
        content = Path(file).read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        self.enabled = parsed.get("enabled", True) if isinstance(parsed, dict) else True
        self.delay = parsed.get("delay", 60) if isinstance(parsed, dict) else 60
        self.priority = parsed.get("priority", 99) if isinstance(parsed, dict) else 99
        self._valid = "invalid" not in content and isinstance(self.enabled, bool)
        self.started = 0
        self.stopped = 0
        self.runs = 0
        self.instances.append(self)

    def start(self) -> None:
        self.started += 1

    def stop(self) -> bool:
        self.stopped += 1
        return True

    def run(self) -> None:
        self.runs += 1

    @property
    def valid(self) -> bool:
        return self._valid


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


@pytest.mark.parametrize(("enabled", "starts"), [(True, 1), (False, 0)])
def test_parallel_manager_respects_flow_enabled(
    manager: runner.FlowManager, tmp_path: Path, enabled: bool, starts: int
) -> None:
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text(yaml.safe_dump({"enabled": enabled}), encoding="utf-8")

    manager.run()

    assert manager._flows[str(flow_file)].started == starts


def test_parallel_manager_starts_flow_when_enabled_is_missing(
    manager: runner.FlowManager, tmp_path: Path
) -> None:
    flow_file = tmp_path / "flow.yaml"
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


def test_manager_defers_changed_flow_while_previous_is_alive(
    manager: runner.FlowManager, tmp_path: Path
) -> None:
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text("version: one", encoding="utf-8")
    manager.run()
    original = manager._flows[str(flow_file)]
    original.stop = Mock(return_value=False)
    flow_file.write_text("version: two", encoding="utf-8")

    manager.run()

    assert manager._flows[str(flow_file)] is original
    assert len(FakeFlow.instances) == 1


def test_manager_disables_running_flow_on_reload(
    manager: runner.FlowManager, tmp_path: Path
) -> None:
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text(yaml.safe_dump({"enabled": True}), encoding="utf-8")
    manager.run()
    original = manager._flows[str(flow_file)]
    flow_file.write_text(yaml.safe_dump({"enabled": False}), encoding="utf-8")

    manager.run()

    replacement = manager._flows[str(flow_file)]
    assert original.stopped == 1
    assert replacement.enabled is False
    assert replacement.started == 0


def test_manager_enables_disabled_flow_on_reload(
    manager: runner.FlowManager, tmp_path: Path
) -> None:
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text(yaml.safe_dump({"enabled": False}), encoding="utf-8")
    manager.run()
    original = manager._flows[str(flow_file)]
    flow_file.write_text(yaml.safe_dump({"enabled": True}), encoding="utf-8")

    manager.run()

    replacement = manager._flows[str(flow_file)]
    assert original.stopped == 1
    assert replacement.enabled is True
    assert replacement.started == 1


def test_manager_defers_disabling_flow_while_previous_is_alive(
    manager: runner.FlowManager, tmp_path: Path
) -> None:
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text(yaml.safe_dump({"enabled": True}), encoding="utf-8")
    manager.run()
    original = manager._flows[str(flow_file)]
    original.stop = Mock(return_value=False)
    flow_file.write_text(yaml.safe_dump({"enabled": False}), encoding="utf-8")

    manager.run()

    assert manager._flows[str(flow_file)] is original
    assert len(FakeFlow.instances) == 1


def test_invalid_modified_flow_replaces_stale_flow(
    manager: runner.FlowManager, tmp_path: Path
) -> None:
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


def test_sequential_manager_skips_disabled_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeFlow.instances = []
    flow_file = tmp_path / "flow.yaml"
    flow_file.write_text(yaml.safe_dump({"enabled": False}), encoding="utf-8")
    monkeypatch.setenv("CFG_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(runner.FlowManager, "start", lambda self: None)
    monkeypatch.setattr(runner, "Flow", FakeFlow)
    monkeypatch.setattr(runner, "cfg", lambda *args, **kwargs: "sequential")

    flow_manager = runner.FlowManager()
    flow_manager.run()

    assert flow_manager._flows[str(flow_file)].runs == 0


def test_sequential_manager_respects_due_times_priority_and_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    FakeFlow.instances = []
    clock = Mock(return_value=100.0)
    execution_order = []
    monkeypatch.setattr(runner.time, "monotonic", clock)
    monkeypatch.setenv("CFG_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(runner.FlowManager, "start", lambda self: None)
    monkeypatch.setattr(runner, "Flow", FakeFlow)
    monkeypatch.setattr(runner, "cfg", lambda *args, **kwargs: "sequential")
    fast_file = tmp_path / "fast.yaml"
    slow_file = tmp_path / "slow.yaml"
    disabled_file = tmp_path / "disabled.yaml"
    fast_file.write_text(yaml.safe_dump({"delay": 1, "priority": 20}), encoding="utf-8")
    slow_file.write_text(yaml.safe_dump({"delay": 5, "priority": 10}), encoding="utf-8")
    disabled_file.write_text(yaml.safe_dump({"enabled": False}), encoding="utf-8")
    flow_manager = runner.FlowManager()

    flow_manager.run()
    fast = flow_manager._flows[str(fast_file)]
    slow = flow_manager._flows[str(slow_file)]
    disabled = flow_manager._flows[str(disabled_file)]
    fast.run = lambda: (execution_order.append("fast"), setattr(fast, "runs", fast.runs + 1))
    slow.run = lambda: (execution_order.append("slow"), setattr(slow, "runs", slow.runs + 1))
    assert [slow.runs, fast.runs, disabled.runs] == [1, 1, 0]

    clock.return_value = 159.0
    flow_manager.run()
    assert [slow.runs, fast.runs] == [1, 1]

    clock.return_value = 160.0
    flow_manager.run()
    assert [slow.runs, fast.runs] == [1, 2]

    clock.return_value = 400.0
    flow_manager.run()
    assert [slow.runs, fast.runs] == [2, 3]
    assert execution_order[-2:] == ["slow", "fast"]

    fast_file.write_text(yaml.safe_dump({"delay": 10, "priority": 20}), encoding="utf-8")
    clock.return_value = 401.0
    flow_manager.run()
    replacement = flow_manager._flows[str(fast_file)]
    assert replacement is not fast
    assert replacement.runs == 1
    assert replacement.started == 0


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


@pytest.mark.parametrize(("configured", "expected"), [(None, True), (True, True), (False, False)])
def test_flow_parses_boolean_enabled(
    tmp_path: Path, configured: bool | None, expected: bool
) -> None:
    data = {"steps": [{"module": "fake", "action": "get"}]}
    if configured is not None:
        data["enabled"] = configured
    flow_file = tmp_path / "enabled.yaml"
    flow_file.write_text(yaml.safe_dump(data), encoding="utf-8")

    flow = runner.Flow(str(flow_file))

    assert flow._valid is True
    assert flow.enabled is expected


@pytest.mark.parametrize("configured", ["false", 1, "yes-as-string"])
def test_flow_rejects_non_boolean_enabled(
    tmp_path: Path, configured: object
) -> None:
    flow_file = tmp_path / "invalid-enabled.yaml"
    flow_file.write_text(yaml.safe_dump({
        "enabled": configured,
        "steps": [{"module": "fake", "action": "get"}],
    }), encoding="utf-8")

    flow = runner.Flow(str(flow_file))

    assert flow._valid is False
    assert flow.enabled is False


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


def test_flow_stop_request_aborts_before_next_step(flow_factory) -> None:
    flow = flow_factory([
        {"name": "first", "module": "fake", "action": "get"},
        {"name": "later", "module": "fake", "action": "follow", "input": "previous"},
    ])
    original_call = flow._call_action

    def stop_after_action(action, inp):
        result = original_call(action, inp)
        flow.stop()
        return result

    flow._call_action = stop_after_action

    flow.run()

    assert ActionModule.calls == [("get", None)]
