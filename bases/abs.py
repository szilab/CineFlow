import sys
import re
from abc import ABC, ABCMeta, abstractmethod
from bases.enums import Phases
from system.config import Config
from bases.request import RequestHandler
from system.logger import log


class SingletonMeta(ABCMeta):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class ModuleBase(ABC, metaclass=SingletonMeta):

    def ready(self) -> bool:
        return bool(getattr(self, '_ready', None))

    def name(self) -> str:
        return getattr(self, '_name', '')

    def run(self, phase: Phases) -> None:
        if not getattr(self, '_ready', None):
            log(f"Skipping '{self.name()}' module as it is not ready, check your settings", level="WARNING")
            return
        if function := getattr(self, phase.name.lower(), None):
            log(f"Running {self.name()} module in the '{phase}' phase")
            function()
        else:
            log(f"{self.name()} does not support the '{phase.name}' phase")

    def _is_required_config_set(self, required_config: list, exit: bool = False) -> None:
        for config in required_config:
            value = getattr(Config(), config, None)
            if not value:
                log(f"The config parameter '{config}' is not set, skipping related tasks!", level="WARNING")
                if exit:
                    log(f"Exiting due to missing configuration for required module '{self.name()}'", level="ERROR")
                    sys.exit(1)
                return False
        return True

    def _init(self, url: str) -> RequestHandler:
        return RequestHandler(url=url)

    def _sn(self, title: str) -> str:
        return re.sub(r'\W+', '', title.replace('.', ' ')).lower()
