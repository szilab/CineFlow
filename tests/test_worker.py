"""Regression tests for worker lifecycle error handling."""

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
