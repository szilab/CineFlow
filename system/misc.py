"""Miscellaneous functions for the system library."""

import os
import importlib
from bases.module import ModuleBase


def module(name: str) -> list:
    """List all modules in the modules directory."""
    directory = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'modules'
    )
    for file in os.listdir(directory):
        if not file.endswith(".py") or file.startswith("__"):
            continue
        if name == file[:-3]:
            module_obj = importlib.import_module(f"{os.path.basename(directory)}.{name}")
            class_name = f"{name[0].capitalize()}{name[1:]}"
            if hasattr(module_obj, class_name) and issubclass(getattr(module_obj, class_name), ModuleBase):
                if class_name.lower() == name.lower():
                    module_class = getattr(module_obj, class_name)
                    return module_class
    return None
