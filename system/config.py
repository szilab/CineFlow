import os
from bases.enums import ConfigParams


class Config():
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Config, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

    def __init__(self) -> None:
        for cfg in ConfigParams:
            if not getattr(self, cfg.name, None):
                if cfg.value[0] == bool:
                    setattr(self, cfg.name, bool(os.getenv(cfg.name, cfg.value[2])))
                elif cfg.value[0] == int:
                    setattr(self, cfg.name, int(os.getenv(cfg.name, cfg.value[2])))
                else:
                    setattr(self, cfg.name, os.getenv(cfg.name, cfg.value[2]))
