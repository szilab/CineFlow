"""CineFlow - Workflow automation system for media processing."""

__version__ = '2.0.0'
__author__ = 'Sandor Szilagyi'
__description__ = 'A workflow automation system for media processing'
__url__ = 'https://github.com/huszilagyisandor/CineFlow'

__title__ = 'cineflow'
__license__ = 'MIT'
__copyright__ = f'Copyright 2025 {__author__}'

# Version info tuple for easy comparison
version_info = tuple(map(int, __version__.split('.')))


def get_version():
    """Return the version string."""
    return __version__


def get_version_info():
    """Return the version info tuple."""
    return version_info
