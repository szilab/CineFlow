"""
This module contains the TaskRunner class,
which is responsible for running the modules in the system.
"""

from datetime import datetime, timedelta
from bases.enums import MediaType, Phases
from bases.utils import list_modules
from system.logger import log
from system.config import cfg


class TaskRunner:
    """TaskRunner class for running app modules."""

    def __init__(self, media_type: MediaType):
        self._type = media_type
        self._running = False

    def run(self):
        """Run the task runner periodically."""
        next_run = datetime.now() - timedelta(seconds=1)
        self._running = True
        while self._running:
            now = datetime.now()
            if now > next_run:
                self.execute()
                next_run = now + timedelta(minutes=cfg(name='interval', category='refresh'))

    def stop(self):
        """Stop the task runner."""
        self._running = False

    def execute(self):
        """Execute the task runner."""
        for phase in Phases:
            log(f"Running {phase.name} phase")
            self.run_phase(phase=phase)
        log(f"Task runner finished for all modules with '{self._type}' type")

    def run_phase(self, phase: Phases):
        """Run a specific phase of the task runner."""
        for module in list_modules():
            if cfg(name='enabled', category=module['name']):
                log(f"Running {module['name']} module")
                module['class'](media_type=self._type).run(phase=phase)
                log(f"Finished {module['name']} module")
            else:
                log(f"Skipping {module['name']} module as it is disabled")
        log(f"Finished {phase.name} phase")
