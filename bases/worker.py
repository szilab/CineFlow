"""Worker base class."""

import random
from abc import ABC, abstractmethod
from threading import Thread
from time import sleep


class WorkerBase(ABC):
    """Base class for workers."""
    def __init__(self):
        self._running = False
        self._delay = 3
        self._thread = None
        self.name = self.__class__.__name__.lower()

    @abstractmethod
    def run(self) -> None:
        """Worker to do."""

    def worker(self) -> None:
        """Worker thread for the consumer."""
        sleep(random.randint(1, self._delay))
        while self._running:
            self.run()
            sleep(self._delay * 60)

    def start(self) -> None:
        """Start the consumer."""
        self._running = True
        self._thread = Thread(target=self.worker)
        self._thread.start()

    def stop(self) -> None:
        """Stop the consumer."""
        self._running = False
        self._thread.join()
        self._thread = None
