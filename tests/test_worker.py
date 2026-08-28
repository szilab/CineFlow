"""Regression tests for worker lifecycle error handling."""

import threading

from cineflow.core.bases.worker import WorkerBase


class FailingWorker(WorkerBase):
    """Worker that fails once, then completes a normal iteration."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def run(self) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("failure")
        self.stop()


def test_worker_logs_exceptions_without_terminating_the_loop(monkeypatch) -> None:
    messages = []
    monkeypatch.setattr("cineflow.core.bases.worker.log", lambda message, level: messages.append((message, level)))
    worker = FailingWorker()
    monkeypatch.setattr(worker._stop_event, "wait", lambda timeout: False)
    worker._running = True

    worker.worker()

    assert worker.calls == 2
    assert worker._running is False
    assert messages == [("Worker 'failingworker' failed: failure", "ERROR")]


class BlockingWorker(WorkerBase):
    """Worker controlled by events for deterministic lifecycle tests."""

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def run(self) -> None:
        self.entered.set()
        self.release.wait()


def test_worker_stop_reports_success_and_clears_terminated_thread() -> None:
    worker = BlockingWorker()
    worker.start()
    assert worker.entered.wait(timeout=1)
    worker.release.set()

    assert worker.stop(timeout=1) is True
    assert worker._thread is None


def test_worker_stop_reports_timeout_and_retains_alive_thread() -> None:
    worker = BlockingWorker()
    worker.start()
    assert worker.entered.wait(timeout=1)
    thread = worker._thread

    assert worker.stop(timeout=0) is False
    assert worker._thread is thread
    assert thread.is_alive()

    worker.release.set()
    assert worker.stop(timeout=1) is True
