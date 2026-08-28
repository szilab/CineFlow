"""Shared pytest fixtures."""

from pathlib import Path

import pytest

from cineflow.core.bases.singleton import SingletonMeta
from cineflow.core.config import Config


@pytest.fixture(autouse=True)
def isolated_config_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Give every test a writable configuration file and fresh singleton."""
    config_directory = tmp_path / "config"
    monkeypatch.setenv("CFG_DIRECTORY", str(config_directory))
    SingletonMeta._instances.pop(Config, None)
    yield config_directory
    SingletonMeta._instances.pop(Config, None)
