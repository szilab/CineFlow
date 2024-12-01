import os
import importlib
import json
import sys
import re
from pathlib import Path
from bases.module import ModuleBase
from system.logger import log


def app_root() -> str:
    """Get the root directory of the application."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def envsubst(string: str) -> str:
    """Substitute environment variables in a string."""
    for key in os.environ.keys():
        if os.getenv(key):
            string = string.replace(f"${key}", os.getenv(key))
    return string


def list_modules() -> list:
    """List all available modules."""

    # get system and user module directories
    system_modules_dir = f"{app_root()}/sys_modules"
    user_modules_dir = f"{app_root()}/user_modules"

    modules = []
    for dir in [system_modules_dir, user_modules_dir]:

        # skip if directory does not exist
        if not os.path.exists(dir):
            continue

        # load modules files from directory
        for file in os.listdir(dir):

            # skip if not a python file or private module
            if not file.endswith(".py") and file.startswith("__"):
                continue

            # import module and check if it is a valid module
            module_name = file[:-3]
            module = importlib.import_module(f"{os.path.basename(dir)}.{module_name}")
            if hasattr(module, "Module") and issubclass(module.Module, ModuleBase):
                modules.append(module.Module)
            else:
                log(f"Module '{module_name}' is not valid", level="ERROR")
                sys.exit(1)
    return modules


def write_json(path: Path, data: dict) -> None:
    """Write a dictionary as JSON to a file."""
    path.write_text(json.dumps(data, indent=4))


def read_json(path: Path) -> dict:
    """Read a JSON file and return as a dictionary."""
    if path.exists():
        return json.loads(path.read_text())
    return {}

def sanitize_name(name: str) -> str:
    """Sanitize a string to be used as a filename or directory name."""
    sanitized = re.sub(r'[\\/\*\?:"<>\|@]', "", name).lower()
    sanitized = sanitized.replace('á', 'a')
    sanitized = sanitized.replace('é', 'e')
    sanitized = sanitized.replace('í', 'i')
    sanitized = sanitized.replace('ó', 'o')
    sanitized = sanitized.replace('ő', 'o')
    sanitized = sanitized.replace('ú', 'u')
    sanitized = sanitized.replace('ü', 'u')
    sanitized = sanitized.replace('ñ', 'n')
    sanitized = sanitized.replace("&", "and").strip()
    return sanitized