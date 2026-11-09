"""Shared pytest fixtures."""

from pathlib import Path

import pytest

from cineflow.core.bases.singleton import SingletonMeta
from cineflow.core.config import Config
from cineflow.utils.directory import CleanupScheduler


@pytest.fixture(autouse=True)
def isolated_config_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Give every test its own application root (CINEFLOW_HOME) and a fresh config singleton."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("EXPORT_DIRECTORY", raising=False)
    config_directory = tmp_path / "home" / "cineflow" / "config"
    SingletonMeta._instances.pop(Config, None)
    yield config_directory
    SingletonMeta._instances.pop(Config, None)


@pytest.fixture(autouse=True)
def stop_library_cleanups():
    """Stop background library cleanup workers started by a test."""
    yield
    assert CleanupScheduler().stop()
