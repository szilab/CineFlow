"""Main entry point for the application"""

import signal
import threading
import sys
from bases.enums import MediaType
from system.logger import log
from system.runner import TaskRunner
from system.config import Config


THREADS = []


def stop(sig, frame):
    """Stop the application"""
    log(f"Stop signal received, exiting! ({sig}), ({frame})")
    for thread in THREADS:
        thread.stop()
    sys.exit(0)


def main():
    """Main entry point for the application"""
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    if Config().twshows:
        log("TV shows enabled")
        THREADS.append(threading.Thread(target=TaskRunner(media_type=MediaType.TV).run).start())
    THREADS.append(threading.Thread(target=TaskRunner(media_type=MediaType.MOVIE).run).start())


if __name__ == "__main__":
    main()
