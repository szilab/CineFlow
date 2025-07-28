"""Worker base class."""

import random
from abc import ABC, abstractmethod
from threading import Thread, Event


class WorkerBase(ABC):
    """Base class for workers."""
    def __init__(self):
        self._running = False
        self._delay = 3
        self._thread = None
        self._first_run = True
        self._stop_event = Event()

    @abstractmethod
    def run(self) -> None:
        """Worker to do."""
        if self._first_run:
            self._first_run = False
            delay = random.randint(1, min(10, self._delay))
            self._stop_event.wait(timeout=delay)

    def worker(self) -> None:
        """Worker thread for the consumer."""
        while self._running:
            self.run()
            self._stop_event.wait(timeout=self._delay * 60)

    def start(self) -> None:
        """Start the consumer."""
        self._running = True
        self._stop_event.clear()
        if self._thread and self._thread.is_alive():
            return
        self._thread = Thread(
            target=self.worker,
            daemon=True,
            name=self.__class__.__name__.lower()
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the consumer."""
        self._running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    @property
    def delay(self) -> int:
        """Get the delay between runs."""
        return self._delay

    @delay.setter
    def delay(self, value: int) -> None:
        """Set the delay between runs."""
        self._delay = max(value, 1)
