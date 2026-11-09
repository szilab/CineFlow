"""Resolve the runtime paths of CineFlow.

Everything CineFlow writes lives below one application root (``CINEFLOW_HOME``):
``$XDG_CONFIG_HOME/cineflow`` (default ``~/.config/cineflow``) on Linux and
macOS, ``%APPDATA%\\cineflow`` on Windows. The Docker image sets
``XDG_CONFIG_HOME=/data``. Only the export library root may live elsewhere:
the ``EXPORT_DIRECTORY`` environment variable or the library module's
``export_directory`` setting moves it.
"""

import os
import sys
from pathlib import Path

APPLICATION_FOLDER = 'cineflow'
EXPORT_ENVIRONMENT = 'EXPORT_DIRECTORY'


def application_root() -> Path:
    """Return the application root (CINEFLOW_HOME) of this platform."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA') or Path.home() / 'AppData' / 'Roaming'
    else:
        base = os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config'
    return (Path(base).expanduser() / APPLICATION_FOLDER).resolve()


def config_directory() -> Path:
    """Return the directory of config.yaml and the flow files."""
    return application_root() / 'config'


def export_directory(configured: str | None = None) -> Path:
    """Return the export library root.

    ``EXPORT_DIRECTORY`` wins over the configured value (the library module's
    ``export_directory``); without either it is ``<CINEFLOW_HOME>/library``.
    Relative paths are relative to the application root.
    """
    value = os.environ.get(EXPORT_ENVIRONMENT) or configured
    if not value:
        return application_root() / 'library'
    path = Path(value).expanduser()
    return (path if path.is_absolute() else application_root() / path).resolve()


def debug_directory() -> Path:
    """Return the directory of the data export and import files."""
    return application_root() / 'debug'


def database_file() -> Path:
    """Return the SQLite cache database file."""
    return application_root() / 'cachedb.sqlite3'
