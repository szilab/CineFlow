"""Canonical runtime version lookup."""

import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def get_version() -> str:
    """Return CineFlow's package version in source, installed, and frozen builds."""
    try:
        return version("cineflow")
    except PackageNotFoundError:
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
        return (bundle_root / "VERSION").read_text(encoding="utf-8").strip()


__version__ = get_version()
