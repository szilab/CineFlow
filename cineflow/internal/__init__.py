"""
Internal CineFlow modules.

Modules that use the module system but are not external API integrations.
"""
from importlib import import_module
import sys
from typing import Any


MODULES = {
    "Library": "library",
    "Tools": "tools",
}

__all__ = tuple(MODULES)


def __getattr__(name: str) -> Any:
    """Load exported internal classes only when they are requested."""
    module_name = MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def load_module(name: str) -> Any:
    """Load an internal class by its workflow module name."""
    class_name = next((key for key, module in MODULES.items() if module == name), None)
    return getattr(sys.modules[__name__], class_name) if class_name else None
