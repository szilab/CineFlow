"""Test runs of a flow: real reads, no side effects.

A test run executes the steps of a (possibly unsaved) flow up to a chosen step
with the normal runtime input and failure semantics, and reports a short
preview of each step output. Actions that change anything outside CineFlow
(adding torrents, writing or deleting library items, exporting files) are not
called: their item input is passed on unchanged and the step is reported as
skipped.
"""

import math
import threading
import time
from collections import OrderedDict
from typing import Any
from uuid import uuid4

from cineflow.core import catalog
from cineflow.core.logger import log, log_context, recent_logs, redact_secrets
from cineflow.core.runner import Flow
from cineflow.core.schema import run_kinds

PREVIEW_ITEMS = 25      # items per page of a step preview
PREVIEW_LIMIT = 2000    # items of a step kept for paging
KEPT_TESTS = 5          # finished tests whose pages can still be read
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


def preview_output(output: Any, limit: int = PREVIEW_ITEMS) -> dict:
    """Describe a step output: item count and the first ``limit`` items."""
    if output is None:
        return {'count': None, 'items': []}
    if isinstance(output, dict):
        output = [output]
    if not isinstance(output, list):
        return {'count': 1, 'items': [{'value': _preview_value(output)}]}
    items = [_preview_value(item) if isinstance(item, dict) else {'value': _preview_value(item)}
             for item in output[:limit]]
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
        self.id = uuid4().hex
        self.context = f"test:{self.id[:8]}"
        self.steps: list[dict] = []
        # previews of all kept items per step result, for paging; taken when the
        # step ends, so later steps that change the items do not alter them
        self.pages: list[list] = []
        self.status = 'running'
        # media kind of the pass in progress, reported only for flows of kind 'both'
        self.kind: str | None = None

    def _step_result(self, index: int, step: dict, status: str, output: Any = None,
                     message: str | None = None, started: float | None = None) -> dict:
        result = {
            'index': index,
            'name': step.get('name'),
            'status': status,
            'message': message,
            'duration': round(time.monotonic() - started, 3) if started else 0,
            'kind': self.kind,
        }
        kept = preview_output(output, PREVIEW_LIMIT)
        result.update(count=kept['count'], items=kept['items'][:PREVIEW_ITEMS], kept=len(kept['items']))
        self.pages.append(kept['items'])
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
        """Execute the steps up to ``until``, once per media kind of the flow."""
        kinds = run_kinds(self.flow.kind)
        with log_context(self.context):
            steps = self.flow.steps if self.until is None else self.flow.steps[: self.until + 1]
            for kind in kinds:
                self.flow.run_kind = kind
                self.kind = kind if len(kinds) > 1 else None
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
            'id': self.id,
            'page_size': PREVIEW_ITEMS,
            'status': self.status,
            'steps': list(self.steps),
            'logs': recent_logs(flow=self.context, limit=100),
        }


_running = threading.BoundedSemaphore(2)
_kept: OrderedDict[str, FlowTest] = OrderedDict()
_kept_lock = threading.Lock()


def _keep(test: FlowTest) -> None:
    """Keep a finished test for paging; the oldest ones are dropped."""
    with _kept_lock:
        _kept[test.id] = test
        while len(_kept) > KEPT_TESTS:
            _kept.popitem(last=False)


def result_page(test_id: str, position: int, page: int) -> dict | None:
    """Return one page of the items of a step result, or None when it is not kept."""
    with _kept_lock:
        test = _kept.get(test_id)
    if test is None or not 0 <= position < len(test.pages) or page < 0:
        return None
    items = test.pages[position]
    pages = max(1, math.ceil(len(items) / PREVIEW_ITEMS))
    if page >= pages:
        return None
    return {
        'items': items[page * PREVIEW_ITEMS:(page + 1) * PREVIEW_ITEMS],
        'page': page, 'pages': pages, 'count': test.steps[position]['count'], 'kept': len(items),
    }


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
        _keep(test)
        return test.result()
    finally:
        _running.release()
