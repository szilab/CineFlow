"""Main entry point for the application"""

import signal
import threading
import sys
from bases.enums import MediaType
from system.logger import log
from system.runner import TaskRunner
from system.config import cfg


THREADS = []


def stop(sig, frame):
    """Stop the application"""
    log(f"Stop signal received, exiting! ({sig}), ({frame})")
    for thread in THREADS:
        thread.stop()
    sys.exit(0)


def main():
    """Main entry point for the application"""
    log("Starting up")
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    found_any = False
    if cfg(name='twshows', category='refresh'):
        log("TV shows enabled")
        found_any = True
        THREADS.append(threading.Thread(target=TaskRunner(media_type=MediaType.TV).run).start())
    if cfg(name='movies', category='refresh'):
        log("Movies enabled")
        found_any = True
        THREADS.append(threading.Thread(target=TaskRunner(media_type=MediaType.MOVIE).run).start())
    if not found_any:
        log("No media types enabled, check config! Exiting!")
        sys.exit(0)


if __name__ == "__main__":
    main()
