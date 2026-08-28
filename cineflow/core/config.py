"""Config module"""

import os
import threading
from typing import Any
from pathlib import Path
import yaml
from yaml import YAMLError
from cineflow.core.bases.singleton import SingletonMeta
from cineflow.core.logger import log


def cfg(key: str, value: Any = None, default: Any = None, required: bool = False):
    """Get/Set a configuration value"""
    if value is not None:
        Config().set(key, value)
    if required and not Config().get(key):
        raise ValueError(f"Configuration key '{key}' is required but not set.")
    return Config().get(key=key, default=default)


class Config(metaclass=SingletonMeta):
    """Manage configuration values"""

    def __init__(self):
        self._file = os.path.join(os.environ.get("CFG_DIRECTORY", "/config"), "config.yaml")
        self._lock = threading.Lock()
        self._mandatory = []
        if not os.path.exists(self._file):
            Path(self._file).parent.mkdir(parents=True, exist_ok=True)
            Path(self._file).touch()
        log(f"Config file '{os.path.basename(self._file)}' initialized.")

    def get(self, key: str, default=None):
        """Get a configuration value"""
        with self._lock:
            return self.getfrom(config=self._load(), key=key, default=default)

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

    def _load(self) -> dict:
        """Load configuration"""
        try:
            with open(self._file, mode="r", encoding='UTF-8') as file:
                config = yaml.safe_load(file)
        except (FileNotFoundError, YAMLError) as e:
            log(f"Error loading config file '{os.path.basename(self._file)}': {e}", level="ERROR")
        return config or {}

    def _save(self, data: dict):
        """Save configuration"""
        try:
            with open(self._file, mode="w", encoding='UTF-8') as file:
                yaml.safe_dump(data, file, default_flow_style=False, allow_unicode=True)
        except (OSError, YAMLError) as e:
            log(f"Error saving config file '{os.path.basename(self._file)}': {e}", level="ERROR")

    @staticmethod
    def getfrom(config: dict, key: str, module: str = None, default: Any = None) -> Any:
        """Get a value from a given config dictionary"""
        value = config.get(key) if key in config else None
        if key not in config:
            value = config
            for current_key in key.split("."):
                if isinstance(value, dict) and current_key in value:
                    value = value[current_key]
                else:
                    value = None
                    break
        hint = value if value is not None else default
        environment_key = f"{module}_{key}".upper() if module else None
        if environment_key and environment_key in os.environ:
            return Config._convert_environment(os.environ[environment_key], hint, environment_key)
        if value is None and default is not None:
            return default
        return value

    @staticmethod
    def _convert_environment(value: str, hint: Any, key: str) -> Any:
        """Convert an environment override only when configuration supplies a type hint."""
        try:
            if isinstance(hint, bool):
                normalized = value.casefold()
                if normalized in {"true", "1", "yes", "on"}:
                    return True
                if normalized in {"false", "0", "no", "off"}:
                    return False
                raise ValueError("expected true/false, 1/0, yes/no, or on/off")
            if isinstance(hint, int):
                return int(value)
            if isinstance(hint, float):
                return float(value)
            return value
        except ValueError as exc:
            raise ValueError(
                f"Invalid environment value for '{key}': {value!r} ({exc})"
            ) from exc
