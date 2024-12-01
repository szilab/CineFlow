import threading
from datetime import datetime
from bases.singleton import Singleton


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


class Logger(metaclass=Singleton):

    def __init__(self, level: str = None, file: str = None, colors: bool = None):
        self._level = level if level else "INFO"
        self._file = file if file else None
        self._colors = colors if colors else True
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

    def exists(self, *path: str):
        for p in path:
            if not self.get(p):
                self.log(f"Missing required config '{p}'", level='ERROR')
                return False


    # @staticmethod
    # def _log(level, message):
    #     if not Logger._should_log(level):
    #         return
    #     timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    #     level_str = f"[{level}]".ljust(8)
    #     if Logger.use_colors:
    #         message = Logger.log_colors[level] + f"{level_str} {message}" + Logger.log_colors["ENDC"]
    #     else:
    #         message = f"{level_str} {message}"
    #     log_message = f"[{timestamp}] {message}"
    #     print(log_message)
    #     if not Logger.log_file:
    #         return
    #     with Logger.lock:
    #         with open(Logger.log_file, "a") as f:
    #             f.write(log_message + "\n")

    # @staticmethod
    # def info(message):
    #     Logger._log("INFO", message)

    # @staticmethod
    # def warning(message):
    #     Logger._log("WARNING", message)

    # @staticmethod
    # def error(message):
    #     Logger._log("ERROR", message)

    # @staticmethod
    # def debug(message):
    #     Logger._log("DEBUG", message)