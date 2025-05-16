"""Config module"""

import os
import threading
from pathlib import Path

import yaml
from bases.singleton import SingletonMeta


def cfg(key: str, value=None, default=None):
    """Get/Set a configuration value"""
    if value is not None:
        Config().set(key, value)
    return Config().get(key, default)


class Config(metaclass=SingletonMeta):
    """Manage configuration values"""

    def __init__(self):
        self._file = os.environ.get("DATA_DIRECTORY" ,"/data") + "/config.yaml"
        self._lock = threading.Lock()
        self._mandatory = []
        if not os.path.exists(self._file):
            Path(self._file).parent.mkdir(parents=True, exist_ok=True)
            Path(self._file).touch()

    def _load(self) -> dict:
        """Load configuration"""
        with open(self._file, mode="r", encoding='UTF-8') as file:
            config = yaml.safe_load(file)
        return config or {}

    def _save(self, data: dict):
        """Save configuration"""
        with open(self._file, mode="w", encoding='UTF-8') as file:
            yaml.safe_dump(data, file, default_flow_style=False, allow_unicode=True)

    def get(self, key: str, default=None):
        """Get a configuration value"""
        if key.capitalize() in os.environ:
            return os.environ[key.capitalize()]
        with self._lock:
            config = self._load()
            if key in config:
                return config[key]
            for current_key in key.split("."):
                if current_key in config:
                    config = config[current_key]
                else:
                    config = None
                    break
        return config or default

    def set(self, key: str, value):
        """Set a configuration value"""
        with self._lock:
            config = self._load()
            if '.' not in key:
                config[key] = value
            else:
                leaf = config
                for current_key in key.split(".")[:-1]:
                    if current_key not in leaf:
                        leaf[current_key] = {}
                    leaf = leaf[current_key]
                leaf[key.split(".")[-1]] = value
            self._save(config)
