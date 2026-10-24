"""
Internal CineFlow modules.

Modules that use the module system but are not external API integrations.
"""
# Pylint cannot infer exports supplied by the module-level __getattr__ registry.
# pylint: disable=undefined-all-variable

from cineflow.utils.registry import lazy_registry


MODULES = {
    "Library": "library",
    "Tools": "tools",
}

__all__ = tuple(MODULES)

__getattr__, load_module = lazy_registry(__name__, MODULES)
