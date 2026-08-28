"""Regression tests for worker lifecycle error handling."""

from cineflow.core.bases.worker import WorkerBase


class FailingWorker(WorkerBase):
    """Worker that stops after one failing iteration."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def run(self) -> None:
        self.calls += 1
        self._running = False
        self._stop_event.set()
        raise RuntimeError("failure")


def test_worker_logs_exceptions_without_terminating_the_loop(monkeypatch) -> None:
    messages = []
    monkeypatch.setattr("cineflow.core.bases.worker.log", lambda message, level: messages.append((message, level)))
    worker = FailingWorker()
    worker._running = True

    worker.worker()

    assert worker.calls == 1
    assert messages == [("Worker 'failingworker' failed: failure", "ERROR")]
