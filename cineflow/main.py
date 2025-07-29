"""Main"""

import time
from cineflow.system.logger import log
from cineflow.system.config import Config
from cineflow.system.database import Database
from cineflow.system.runner import FlowManager


class MainApp:
    """Class to manage the application lifecycle"""

    def __init__(self):
        """Initialize the application"""
        log("Application started", level="MSG")
        self._components = []
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
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log("Application stopped by input", level="INFO")
            self.shutdown()

    def shutdown(self):
        """Shutdown the application gracefully"""
        for component in reversed(self._components):
            log(f"Stopping component: {component.__class__.__name__}", level="MSG")
            if hasattr(component, 'close') and callable(getattr(component, 'close')):
                component.close()
            if hasattr(component, 'stop') and callable(getattr(component, 'stop')):
                component.stop()
        log("Application shutdown complete", level="INFO")


def main():
    """Main function"""
    app = MainApp()
    app.run()


if __name__ == '__main__':
    main()
