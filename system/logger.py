"""Logger module for logging messages to the console."""
import os
import sys
import threading
from datetime import datetime
from enum import Enum

def log(*values, level: str = 'DEBUG'):
    """Shortcut to log a message to the console."""
    Logger().log(*values, level=level)


class LogLevels(Enum):
    """Log levels for the logger."""
    DEBUG = 1
    MSG = 2
    INFO = 3
    WARNING = 4
    ERROR = 5


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

    def log(self, message, level: str = 'DEBUG'):
        """Log a message to the console."""
        if not self._should_log(level):
            return
        with self._lock:
            thread = threading.current_thread().name
            thread = thread.replace('MainThread', 'main')
            message = (
                f"[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] " +
                f" ({level} from {thread[:10]})".ljust(26) +
                message
            )
            if self._colors:
                message = LogColors[level].value + message + LogColors['ENDC'].value
            # prevent logging from being interrupted by other threads
            sys.stdout.write(message + '\n')
            sys.stdout.flush()
