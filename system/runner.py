from datetime import datetime, timedelta
from system.config import Config
from bases.enums import MediaType, Phases
from bases.utils import list_modules
from system.logger import log


class TaskRunner:
    def __init__(self, type: MediaType):
        self._type = type
        self._running = False

    def run(self):
        next_run = datetime.now() - timedelta(seconds=1)
        self._running = True
        while self._running:
            now = datetime.now()
            if now > next_run:
                self.execute()
                next_run = now + timedelta(minutes=Config().INTERVAL)

    def stop(self):
        self._running = False

    def execute(self):
        for phase in Phases:
            log(f"Running {phase.name} phase")
            self.run_phase(phase=phase)

    def run_phase(self, phase: Phases):
        for module in list_modules():
            log(f"Running {module['name']} module")
            module['class'](type=self._type).run(phase=phase)
            log(f"Finished {module['name']} module")
