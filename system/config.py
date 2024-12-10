"""App config module"""

import os
from os import path
import sys
import json
from typing import Any
from jsonschema import Draft7Validator


def cfg(name: str, category: str, value: Any = None) -> str:
    """Shortcut for Config get and set"""
    if value is not None:
        Config().set(name=name, category=category, value=value)
        return value
    return Config().get(name, category)


class Config():
    """App configuration"""
    _instances = {}

    def __call__(self, *args, **kwargs):
        if self not in self._instances:
            self._instances[self] = super(Config, self).__call__(*args, **kwargs)  # pylint: disable=no-member
        return self._instances[self]

    def __init__(self) -> None:
        self._data_dir = os.getenv('DATA_DIR', '/data')
        self._app_dir = path.dirname(path.dirname(__file__))

        self._schema_file = f"{self._app_dir}/schema.json"
        self._config_file = f"{self._data_dir}/config.json"
        self.config = {}

        with open(self._schema_file, 'r', encoding='UTF-8') as f:
            schema = json.load(f)
        if os.path.exists(self._config_file):
            with open(self._config_file, 'r', encoding='UTF-8') as f:
                config = json.load(f)
        else:
            config = {}
        self._validate_and_apply_defaults(config=config, schema=schema)
        self._overwrite_from_env()

    def get_data_dir(self) -> str:
        """Get data directory"""
        return self._data_dir

    def get(self, name: str, category: str) -> str:
        """Get config value"""
        if category in self.config:
            return self.config[category].get(name, None)
        return None

    def set(self, name: str, category: str, value: Any) -> None:
        """Set config value"""
        if category not in self.config:
            self.config[category] = {}
        self.config[category][name] = value
        self._save()

    def _save(self) -> None:
        with open(f"{self._data_dir}/config.json", 'w', encoding='UTF-8') as f:
            f.write(json.dumps(self.config, indent=4))

    def _overwrite_from_env(self) -> None:
        """Overwrite config from environment variables"""
        for key in self.config.keys():
            for e in os.environ:
                if e.startswith(f"{key.upper()}_"):
                    category = key
                    _, name = e.split('_', 1)
                    if os.getenv(e) == 'true':
                        self.config[category][name.lower()] = True
                    elif os.getenv(e) == 'false':
                        self.config[category][name.lower()] = False
                    elif os.getenv(e).isdigit():
                        self.config[category][name.lower()] = int(os.getenv(e))
                    else:
                        self.config[category][name.lower()] = os.getenv(e)

    def _validate_and_apply_defaults(self, config: dict, schema: dict) -> None:
        validator = Draft7Validator(schema=schema)
        for error in sorted(validator.iter_errors(config), key=lambda e: e.path):
            print(f"Config validation error: {error.message} at {list(error.path)}")
            sys.exit(1)
        self.config = self._apply_defaults(instance=config, schema=schema)

    @staticmethod
    def _apply_defaults(instance: dict, schema: dict) -> dict:
        """recursively apply defaults to instance"""
        if "properties" in schema:
            for key, value in schema["properties"].items():
                if key not in instance and "default" in value:
                    instance[key] = value.get("default")
                if "properties" in value:
                    instance[key] = Config._apply_defaults(instance.get(key, {}), value)
        if "default" in schema:
            instance = schema.get("default")
        return instance
