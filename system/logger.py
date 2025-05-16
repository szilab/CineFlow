"""Logger module for logging messages to the console."""
import os
import threading
from datetime import datetime
from enum import Enum

def log(*values, level: str = 'INFO'):
    """Shortcut to log a message to the console."""
    Logger().log(*values, level=level)


class LogLevels(Enum):
    """Log levels for the logger."""
    DEBUG = 1
    MSG = 2
    INFO = 2
    WARNING = 3
    ERROR = 4


class LogColors(Enum):
    """Log colors for the logger."""
    DEBUG = '\033[96m'
    MSG = '\033[92m'
    INFO = '\033[37m'
    WARNING = '\033[93m'
    ERROR = '\033[91m'
    ENDC = '\033[0m'


class Logger():
    """Logger class for logging messages to the console."""

    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, 'instance'):
            cls.instance = super(Logger, cls).__new__(cls, *args, **kwargs)
        return cls.instance

    def __init__(self):
        self._level = LogLevels[os.environ.get('LOG_LEVEL', 'INFO')]
        self._colors = bool(os.environ.get('LOG_COLORS', False))
        self._lock = threading.Lock()

    def _should_log(self, level):
        return LogLevels[level].value >=self._level.value

    def log(self, message, level: str = 'INFO'):
        """Log a message to the console."""
        if not self._should_log(level):
            return
        message = (
            f"[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] " +
            f"[{level}]".ljust(10) +
            message
        )
        if self._colors:
            message = LogColors[level].value + message + LogColors['ENDC'].value
        print(message)
