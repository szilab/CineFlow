"""Lazy class registry shared by the workflow module packages."""

from importlib import import_module
import sys
from typing import Any, Callable


def lazy_registry(package: str, modules: dict[str, str]) -> tuple[Callable, Callable]:
    """Return the ``__getattr__`` and ``load_module`` functions for a package.

    ``modules`` maps exported class names to submodule names, which are also the
    module names used in workflow YAML.
    """

    def __getattr__(name: str) -> Any:  # pylint: disable=invalid-name
        """Load exported classes only when they are requested."""
        module_name = modules.get(name)
        if module_name is None:
            raise AttributeError(f"module {package!r} has no attribute {name!r}")
        value = getattr(import_module(f"{package}.{module_name}"), name)
        setattr(sys.modules[package], name, value)
        return value

    def load_module(name: str) -> Any:
        """Load a class by its workflow module name."""
        class_name = next((key for key, module in modules.items() if module == name), None)
        return getattr(sys.modules[package], class_name) if class_name else None

    return __getattr__, load_module
