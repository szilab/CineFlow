"""Test runs of a flow: real reads, no side effects.

A test run executes the steps of a (possibly unsaved) flow up to a chosen step
with the normal runtime input and failure semantics, and reports a short
preview of each step output. Actions that change anything outside CineFlow
(adding torrents, writing or deleting library items, exporting files) are not
called: their item input is passed on unchanged and the step is reported as
skipped.
"""

import threading
import time
from typing import Any
from uuid import uuid4

from cineflow.core import catalog
from cineflow.core.logger import log, log_context, recent_logs, redact_secrets
from cineflow.core.runner import Flow

PREVIEW_ITEMS = 25
TEXT_LIMIT = 300
DEFAULT_TIMEOUT = 180


def _preview_value(value: Any) -> Any:
    """Return a short, JSON-safe and credential-free value."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_preview_value(item) for item in list(value)[:10]]
    if isinstance(value, dict):
        return {str(key): _preview_value(item) for key, item in list(value.items())[:20]}
    text = redact_secrets(str(value))
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT] + '…'


def preview_output(output: Any) -> dict:
    """Describe a step output: item count and the first items."""
    if output is None:
        return {'count': None, 'items': []}
    if isinstance(output, dict):
        output = [output]
    if not isinstance(output, list):
        return {'count': 1, 'items': [{'value': _preview_value(output)}]}
    items = [_preview_value(item) if isinstance(item, dict) else {'value': _preview_value(item)}
             for item in output[:PREVIEW_ITEMS]]
    return {'count': len(output), 'items': items}


def _passthrough(inp: Any) -> Any:
    """Return the item input a skipped action would have received."""
    if isinstance(inp, dict):
        return inp.get('data')
    return inp if isinstance(inp, list) else None


class FlowTest:
    """Runs one test of a flow definition in a background thread."""

    def __init__(self, definition: dict, until: int | None = None) -> None:
        self.flow = Flow('<test>', definition=definition)
        self.until = until
        self.context = f"test:{uuid4().hex[:8]}"
        self.steps: list[dict] = []
        self.status = 'running'

    def _step_result(self, index: int, step: dict, status: str, output: Any = None,
                     message: str | None = None, started: float | None = None) -> dict:
        result = {
            'index': index,
            'name': step.get('name'),
            'status': status,
            'message': message,
            'duration': round(time.monotonic() - started, 3) if started else 0,
            **preview_output(output),
        }
        self.steps.append(result)
        return result

    def _run_step(self, index: int, step: dict) -> bool:  # noqa: C901
        """Run or skip one step; return whether the test may continue."""
        definition = catalog.definition(step.get('module'))
        action = definition.action(step.get('action')) if definition else None
        started = time.monotonic()
        flow = self.flow
        try:
            inp = flow._load_input(step=step)  # pylint: disable=protected-access
            if action is not None and (action.side_effects or action.destructive):
                output = _passthrough(inp)
                self._step_result(index, step, 'skipped', output,
                                  'Not run in a test: this action changes external state.', started)
            else:
                if not (module := flow._load_module(step=step)):  # pylint: disable=protected-access
                    self._step_result(index, step, 'failed', None, 'Module could not be loaded.', started)
                    return False
                if not (call := flow._load_action(inst=module, step=step)):  # pylint: disable=protected-access
                    self._step_result(index, step, 'failed', None, 'Action not found.', started)
                    return False
                output = flow._call_action(action=call, inp=inp)  # pylint: disable=protected-access
                if output is None and step.get('action') == 'get':
                    self._step_result(index, step, 'failed', None,
                                      'Retrieval failed; a real run stops here.', started)
                    return False
                self._step_result(index, step, 'ok', output, None, started)
        except Exception as exc:  # pylint: disable=broad-except
            log(f"Test step '{step.get('name')}' failed: {exc}", level='ERROR')
            self._step_result(index, step, 'failed', None, str(exc), started)
            return False
        if step.get('name'):
            flow._outputs[step['name']] = output  # pylint: disable=protected-access
        flow._outputs['latest'] = output  # pylint: disable=protected-access
        return True

    def run(self) -> None:
        """Execute the steps up to ``until``."""
        with log_context(self.context):
            steps = self.flow.steps if self.until is None else self.flow.steps[: self.until + 1]
            self.flow._outputs = {}  # pylint: disable=protected-access
            for index, step in enumerate(steps):
                if self.flow._stop_event.is_set():  # pylint: disable=protected-access
                    self.status = 'stopped'
                    return
                if not self._run_step(index, step):
                    self.status = 'failed'
                    return
            self.status = 'success'

    def result(self) -> dict:
        """Return the JSON-serializable test report."""
        return {
            'status': self.status,
            'steps': list(self.steps),
            'logs': recent_logs(flow=self.context, limit=100),
        }


_running = threading.BoundedSemaphore(2)


def run_test(definition: dict, until: int | None = None, timeout: float = DEFAULT_TIMEOUT) -> dict | None:
    """Run a flow test and wait for it; None when too many tests are running."""
    if not _running.acquire(blocking=False):
        return None
    try:
        test = FlowTest(definition, until)
        if not test.flow.valid:
            return {'status': 'failed', 'steps': [], 'logs': [],
                    'message': 'The flow has no runnable steps.'}
        thread = threading.Thread(target=test.run, daemon=True, name=f"flow:{test.context}")
        thread.start()
        thread.join(timeout=timeout)
        if thread.is_alive():
            test.flow._stop_event.set()  # pylint: disable=protected-access
            test.status = 'timeout'
        return test.result()
    finally:
        _running.release()
