"""
Internal CineFlow modules.

Modules that use the module system but are not external API integrations.
"""
from importlib import import_module
from typing import Any


_MODULES = {
    "Library": "library",
    "Tools": "tools",
}

__all__ = tuple(_MODULES)


def __getattr__(name: str) -> Any:
    """Load exported internal classes only when they are requested."""
    module_name = _MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value
