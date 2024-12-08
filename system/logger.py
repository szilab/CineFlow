import threading
from datetime import datetime
from system.config import Config


def log(*values, level: str = 'INFO'):
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

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Logger, cls).__call__(*args, **kwargs)
        return cls._instances[cls]

    def __init__(self):
        if Config().LOG_LEVEL in LogLevels:
            self._level = Config().LOG_LEVEL
        else:
            self._level = 'INFO'
        self._colors = Config().LOG_COLORS
        self._lock = threading.Lock()

    def __should_log(self, level):
        return LogLevels[level] >= LogLevels[self._level]

    def log(self, *values, level: str = 'INFO'):
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
