"""Main"""

import signal
import threading
from cineflow.core.logger import log
from cineflow.core.config import Config
from cineflow.core.database import Database
from cineflow.core.runner import FlowManager


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


def main():
    """Main function"""
    app = MainApp()

    def shutdown(_signum, _frame):
        app.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    app.run()


if __name__ == '__main__':
    main()
