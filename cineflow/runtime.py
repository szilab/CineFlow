"""Resolve runtime paths and bootstrap a first-run CineFlow configuration."""

import os
import shutil
import sys
from pathlib import Path


def application_root() -> Path:
    """Return the application root, honoring explicit configuration first."""
    if home := os.environ.get("CINEFLOW_HOME"):
        return Path(home).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd().resolve()


def _runtime_directory(environment_key: str, default_name: str) -> Path:
    """Resolve a directory override or a directory below the application root."""
    if configured := os.environ.get(environment_key):
        return Path(configured).expanduser().resolve()
    return application_root() / default_name


def config_directory() -> Path:
    """Return the effective configuration directory."""
    return _runtime_directory("CFG_DIRECTORY", "config")


def export_directory() -> Path:
    """Return the effective exported-library directory."""
    return _runtime_directory("EXPORT_DIRECTORY", "library")


def media_directory() -> Path:
    """Return the optional external sample-media directory."""
    return _runtime_directory("MEDIA_DIRECTORY", "media")


def bundled_examples_directory() -> Path:
    """Return the shared example configuration source for source or frozen runs."""
    if bundle_root := getattr(sys, "_MEIPASS", None):
        return Path(bundle_root) / "examples"
    return Path(__file__).resolve().parent.parent / "docker" / "examples"


def bootstrap_configuration() -> tuple[Path, ...]:
    """Copy bundled examples into an empty configuration directory once."""
    destination = config_directory()
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        return ()

    source = bundled_examples_directory()
    copied = []
    for filename in ("config.yaml", "from_lib.yaml", "to_lib.yaml"):
        target = destination / filename
        shutil.copy2(source / filename, target)
        copied.append(target)
    return tuple(copied)
