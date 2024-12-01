import os
import sys
import yaml
from typing import Any
from bases.singleton import Singleton
from system.logger import Logger, log
from system.misc import app_root, envsubst


def cfg(path: str, default: Any = None) -> Any:
    """
    Get configuration value.
    :param path: Dot separated configuration path.
    :param default: Default value.
    """
    return Config().get(path, default)


class Config(metaclass=Singleton):

    def __init__(self) -> None:
        # load configuration from <app root>/config.yaml
        try:
            with open(f"{app_root()}/config.yaml", "r") as f:
                self._config = yaml.safe_load(envsubst(f.read()))
        except Exception as e:
            self._config = {}

        # initialize logger
        Logger(level=self.get('log.level'), file=self.get('log.file'), colors=self.get('log.colors'))

        # check if configuration file exists and terminate app if not
        if not self._config:
            log(f"Configuration file '{app_root()}/config.yaml' not found", level='ERROR')
            sys.exit(1)

    def get(self, path: str, default: Any = None) -> Any:
        """
        Get configuration value.
        :param path: Dot separated configuration path.
        :param default: Default value.
        """
        names = path.split('.')
        data = self._config
        try:
            for _, name in enumerate(names):
                data = data[int(name)] if isinstance(data, list) else data[name]
            return data
        except Exception:
            return default

    def set(self, path: str, value: Any) -> None:
        """
        Set configuration value.
        :param path: Dot separated configuration path.
        :param value: Value to set.
        """
        names = path.split('.')
        data = self._config
        try:
            for i, name in enumerate(names):
                if i == len(names) - 1:
                    data[name] = value
                else:
                    if not data.get(name):
                        data[name] = {}
                    data = data[name]
        except Exception as e:
            log(f"Failed to set configuration '{path}': {e}", level='ERROR')

    def required(self, params: list, hint: str = None) -> None:
        """
        Check if required configuration is set exit app if not.
        :param path: Dot separated configuration path.
        :param hint: Additional hint for missing configuration.
        """
        if not isinstance(params, list):
            params = [params]
        for path in params:
            if not self.get(path):
                log(f"Missing required config '{path}' {hint if hint else ''}", level='ERROR')
                sys.exit(1)

    def defaults(self, params: list) -> None:
        """
        Set default configuration values.
        :param list: List of key and value pairs in the form of key=value.
        """
        for item in params:
            if '=' in item:
                path, value = item.split('=')
                if not self.get(path):
                    self.set(path, value)

    # def get(self, key=None, default=None):
    #     if not key:
    #         return self.config
    #     if value := self.__get_path(key=key, node=self.config):
    #         return value
    #     elif value := os.getenv(key.upper().replace("-", "_")):
    #         return value
    #     return default

    # def set(self, key, value):
    #     if '.' not in key:
    #         self.config[key] = value
    #     else:
    #         self.__set_path(key=key, value=value, node=self.config)

    # def params_exists(self, params: list, hint: str = None) -> bool:
    #     for key in params:
    #         if not self.get(key):
    #             Logger.error(f"Missing required config '{key}' {hint if hint else ''}")
    #             sys.exit(1)

    # def __env_substitute(self, string: str) -> str:
    #     for key in os.environ.keys():
    #         string = string.replace(f"${key}", os.getenv(key))
    #     return string

    # def __get_path(self, key, node):
    #     if '.' not in key:
    #         return node.get(key)
    #     else:
    #         root = key.split('.')[0]
    #         key = key.replace(f"{root}.", "")
    #         if root not in node.keys():
    #             return None
    #         return self.__get_path(key=key, node=node[root])

    # def __set_path(self, key, value, node):
    #     if '.' not in key:
    #         node[key] = value
    #         return
    #     else:
    #         root = key.split('.')[0]
    #         key = key.replace(f"{root}.", "")
    #         if root not in node.keys():
    #             node[root] = {}
    #         self.__set_path(key=key, value=value, node=node[root])