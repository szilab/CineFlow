"""
External service integrations.

Each module provides a consumer class that interfaces with an external API.
New integrations should be added here and will be auto-discovered.
"""
from importlib import import_module
from typing import Any


_MODULES = {
    "Tmdb": "tmdb",
    "Jackett": "jackett",
    "Jellyfin": "jellyfin",
    "Plex": "plex",
    "Transmission": "transmission",
}

__all__ = tuple(_MODULES)


def __getattr__(name: str) -> Any:
    """Load exported integration classes only when they are requested."""
    module_name = _MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value
