"""Module base class for all modules to inherit from."""

import sys
import re
from abc import ABC, ABCMeta
from bases.enums import Phases
from bases.request import RequestHandler
from system.config import cfg
from system.logger import log


class SingletonMeta(ABCMeta):
    """Singleton metaclass to ensure only one instance of a class is created."""
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class ModuleBase(ABC, metaclass=SingletonMeta):
    """Base class for all modules to inherit from."""

    def ready(self) -> bool:
        """Check if the module is ready to run."""
        return bool(getattr(self, '_ready', None))

    def name(self) -> str:
        """Return the name of the module."""
        return getattr(self, '_name', '')

    def run(self, phase: Phases) -> None:
        """Run the module in the specified phase."""
        if not getattr(self, '_ready', None):
            log(
                f"Skipping '{self.name()}' module as it is not ready, "
                "check your settings",
                level="WARNING"
            )
            return
        if function := getattr(self, phase.name.lower(), None):
            log(f"Running {self.name()} module in the '{phase.name}' phase")
            function()
        else:
            log(f"{self.name()} does not support the '{phase.name}' phase")

    def _is_required_config_set(
        self,
        names: list[str],
        category: str,
        exit_on_failure: bool = False
    ) -> None:
        for name in names:
            if not cfg(name=name, category=category):
                log(
                    f"The config parameter '{category}.{name}' is not set, "
                    "skipping related tasks!",
                    level="WARNING"
                )
                if exit_on_failure:
                    log(
                        "Exiting due to missing configuration for required module "
                        f"'{self.name()}'",
                        level="ERROR"
                    )
                    sys.exit(1)
                return False
        return True

    def _init(self, url: str) -> RequestHandler:
        return RequestHandler(url=url)

    def _sn(self, title: str) -> str:
        return re.sub(r'\W+', '', title.replace('.', ' ')).lower()
