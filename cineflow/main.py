"""CineFlow application and command-line entry point."""

import argparse
import signal
import threading
from collections.abc import Sequence
from cineflow import __version__
from cineflow.core.logger import log
from cineflow.core.config import Config
from cineflow.core.database import Database
from cineflow.core.runner import FlowManager
from cineflow.runtime import bootstrap_configuration


class MainApp:
    """Class to manage the application lifecycle"""

    def __init__(self):
        """Initialize the application"""
        log("Application started", level="MSG")
        self._components = []
        self._shutdown_event = threading.Event()
        try:
            log("Initialize singleton modules", level="MSG")
            self._components.append(Config())
            self._components.append(Database())
            log("Start FlowManager", level="MSG")
            self._components.append(FlowManager())
        except Exception as e:
            log(f"Error during initialization: {e}", level="ERROR")
            raise

    def run(self):
        """Run the application"""
        try:
            while not self._shutdown_event.wait(timeout=1):
                pass
        except KeyboardInterrupt:
            log("Application stopped by input", level="INFO")
            self.shutdown()

    def shutdown(self):
        """Shutdown the application gracefully"""
        if self._shutdown_event.is_set():
            return
        self._shutdown_event.set()
        for component in reversed(self._components):
            log(f"Stopping component: {component.__class__.__name__}", level="MSG")
            if hasattr(component, 'stop') and callable(getattr(component, 'stop')):
                component.stop()
        safe_to_close = True
        for component in reversed(self._components):
            if not safe_to_close:
                log(
                    f"Leaving component open after worker shutdown timeout: "
                    f"{component.__class__.__name__}", level="WARNING"
                )
                continue
            if hasattr(component, 'close') and callable(getattr(component, 'close')):
                if component.close() is False:
                    safe_to_close = False
        log("Application shutdown complete", level="INFO")


def _parse_args(argv: Sequence[str] | None = None) -> None:
    """Parse informational command-line options before runtime initialization."""
    parser = argparse.ArgumentParser(description="CineFlow media automation worker")
    parser.add_argument("--version", action="version", version=f"CineFlow {__version__}")
    parser.parse_args(argv)


def main(argv: Sequence[str] | None = None):
    """Run the long-lived CineFlow worker."""
    _parse_args(argv)
    bootstrap_configuration()
    app = MainApp()

    def shutdown(_signum, _frame):
        app.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    app.run()


if __name__ == '__main__':
    main()
