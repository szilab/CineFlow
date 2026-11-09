"""Config module"""

import copy
import os
import threading
from typing import Any
from pathlib import Path
import yaml
from yaml import YAMLError
from cineflow.core.bases.singleton import SingletonMeta
from cineflow.core.logger import log
from cineflow.runtime import config_directory


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
        self._file = str(config_directory() / "config.yaml")
        self._lock = threading.Lock()
        self._last_valid = None
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

    def data(self) -> dict:
        """Return a copy of the whole configuration."""
        with self._lock:
            return copy.deepcopy(self._load())

    def replace(self, data: dict) -> None:
        """Replace the whole configuration, keeping a backup of the old file."""
        if not isinstance(data, dict):
            raise ValueError("The configuration must be a mapping.")
        from cineflow.core.store import write_text  # pylint: disable=import-outside-toplevel

        with self._lock:
            write_text(
                Path(self._file),
                yaml.safe_dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False),
            )
            self._last_valid = copy.deepcopy(data)

    def _load(self) -> dict:
        """Load configuration, keeping the last valid state when the file is broken."""
        name = os.path.basename(self._file)
        try:
            with open(self._file, mode="r", encoding='UTF-8') as file:
                config = yaml.safe_load(file)
        except FileNotFoundError:
            log(f"Config file '{name}' not found, using empty configuration.", level="WARNING")
            config = {}
        except (OSError, YAMLError) as e:
            if self._last_valid is None:
                raise ValueError(f"Config file '{name}' cannot be loaded: {e}") from e
            log(
                f"Error loading config file '{name}', using last valid configuration: {e}",
                level="ERROR"
            )
            return copy.deepcopy(self._last_valid)
        if config is None:
            config = {}
        if not isinstance(config, dict):
            if self._last_valid is None:
                raise ValueError(f"Config file '{name}' must contain a mapping.")
            log(
                f"Config file '{name}' must contain a mapping, using last valid configuration.",
                level="ERROR"
            )
            return copy.deepcopy(self._last_valid)
        self._last_valid = copy.deepcopy(config)
        return config

    def _save(self, data: dict):
        """Save configuration"""
        try:
            with open(self._file, mode="w", encoding='UTF-8') as file:
                yaml.safe_dump(data, file, default_flow_style=False, allow_unicode=True)
        except (OSError, YAMLError) as e:
            log(f"Error saving config file '{os.path.basename(self._file)}': {e}", level="ERROR")

    @staticmethod
    def getfrom(config: dict, key: str, module: str = None, default: Any = None, environment: str = None) -> Any:
        """Get a value from a given config dictionary.

        An environment variable overrides the value: ``environment`` when given,
        else ``<MODULE>_<KEY>`` for a module.
        """
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
        environment_key = environment or (f"{module}_{key}".upper() if module else None)
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
