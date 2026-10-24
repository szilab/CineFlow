"""
External service integrations.

Each module provides a consumer class that interfaces with an external API.
New integrations must be registered in ``MODULES``.
"""
# Pylint cannot infer exports supplied by the module-level __getattr__ registry.
# pylint: disable=undefined-all-variable

from cineflow.utils.registry import lazy_registry


MODULES = {
    "Tmdb": "tmdb",
    "Jackett": "jackett",
    "Jellyfin": "jellyfin",
    "Plex": "plex",
    "QBittorrent": "qbittorrent",
    "Transmission": "transmission",
}

__all__ = tuple(MODULES)

__getattr__, load_module = lazy_registry(__name__, MODULES)
