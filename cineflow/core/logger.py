"""Logger module for logging messages to the console."""
import os
import re
import sys
import threading
from datetime import datetime
from enum import Enum


# Credential names that must never reach the log output.
_SECRET_NAMES = r"(?:api[_-]?key|jackett_apikey|token|x-plex-token|passkey|password|sid)"
_SECRET_QUERY = re.compile(rf"(?i)(\b{_SECRET_NAMES}=)[^&\s'\"<>]+")
_SECRET_MAPPING = re.compile(rf"(?i)(['\"]{_SECRET_NAMES}['\"]\s*:\s*['\"])[^'\"]*")


def redact_secrets(message: str) -> str:
    """Mask credential values in URLs and dictionary representations."""
    message = _SECRET_QUERY.sub(r"\1***", message)
    return _SECRET_MAPPING.sub(r"\1***", message)


def log(message, level: str = 'DEBUG'):
    """Shortcut to log a message to the console."""
    Logger().log(message, level=level)


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

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._level = LogLevels[os.environ.get('LOG_LEVEL', 'MSG').upper()]
                instance._colors = os.environ.get('LOG_COLORS', '').strip().casefold() in {
                    'true', '1', 'yes', 'on'
                }
                instance._lock = threading.Lock()
                cls._instance = instance
        return cls._instance

    def _should_log(self, level):
        return LogLevels[level].value >= self._level.value

    def log(self, message, level: str = 'DEBUG'):
        """Log a message to the console."""
        if not self._should_log(level):
            return
        message = redact_secrets(str(message))
        with self._lock:
            thread = threading.current_thread().name
            thread = thread.replace('MainThread', 'main')
            message = (
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] " +
                f" ({level[:4].ljust(4)} from {thread[:28]})".ljust(43) +
                message
            )
            if self._colors:
                message = LogColors[level].value + message + LogColors['ENDC'].value
            # prevent logging from being interrupted by other threads
            sys.stdout.write(message + '\n')
            sys.stdout.flush()
