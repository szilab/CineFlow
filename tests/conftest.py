"""Shared pytest fixtures."""

from pathlib import Path

import pytest

from cineflow.core.bases.singleton import SingletonMeta
from cineflow.core.config import Config
from cineflow.utils.directory import CleanupScheduler


@pytest.fixture(autouse=True)
def isolated_config_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Give every test a writable configuration file and fresh singleton."""
    config_directory = tmp_path / "config"
    monkeypatch.setenv("CFG_DIRECTORY", str(config_directory))
    SingletonMeta._instances.pop(Config, None)
    yield config_directory
    SingletonMeta._instances.pop(Config, None)


@pytest.fixture(autouse=True)
def stop_library_cleanups():
    """Stop background library cleanup workers started by a test."""
    yield
    assert CleanupScheduler().stop()
