"""Logger module for logging messages to the console."""

import threading
from datetime import datetime
from system.config import Config


def log(*values, level: str = 'INFO'):
    """Shortcut to log a message to the console."""
    Logger().log(*values, level=level)


LogLevels = {
    'DEBUG': 1,
    'INFO': 2,
    'WARNING': 3,
    'ERROR': 4,
}


LogColors = {
    'DEBUG': '\033[96m',
    'INFO': '\033[34m',
    'WARNING': '\033[93m',
    'ERROR': '\033[91m',
    'ENDC': '\033[0m',
}


class Logger():
    """Logger class for logging messages to the console."""
    _instances = {}

    def __call__(self, *args, **kwargs):
        if self not in self._instances:
            self._instances[self] = super(Logger, self).__call__(*args, **kwargs)  # pylint: disable=no-member
        return self._instances[self]

    def __init__(self):
        if Config().log_level in LogLevels:
            self._level = Config().log_level
        else:
            self._level = 'INFO'
        self._colors = Config().log_colors
        self._lock = threading.Lock()

    def __should_log(self, level):
        return LogLevels[level] >= LogLevels[self._level]

    def log(self, *values, level: str = 'INFO'):
        """Log a message to the console."""
        if not self.__should_log(level):
            return
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level_str = f"[{level}]".ljust(10)
        if self._colors:
            print(LogColors[level], end="")
        print(f"[{timestamp}] {level_str}", *values, end="")
        if self._colors:
            print(LogColors['ENDC'], end="")
        print()
