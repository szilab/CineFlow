"""Runtime paths: everything lives below one application root (CINEFLOW_HOME)."""

from pathlib import Path

from cineflow import runtime


def test_linux_root_is_below_xdg_config_home(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    root = tmp_path / "cineflow"

    assert runtime.application_root() == root
    assert runtime.config_directory() == root / "config"
    assert runtime.export_directory() == root / "library"
    assert runtime.debug_directory() == root / "debug"
    assert runtime.database_file() == root / "cachedb.sqlite3"


def test_linux_root_defaults_to_dot_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(runtime.Path, "home", lambda: tmp_path)

    assert runtime.application_root() == tmp_path / ".config" / "cineflow"


def test_windows_root_is_below_appdata(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "ignored"))

    assert runtime.application_root() == tmp_path / "cineflow"


def test_old_directory_variables_no_longer_move_folders(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for name in ("CINEFLOW_HOME", "CFG_DIRECTORY", "MEDIA_DIRECTORY", "DB_DIRECTORY", "DEBUG_DIRECTORY"):
        monkeypatch.setenv(name, str(tmp_path / "elsewhere"))

    assert runtime.config_directory() == tmp_path / "cineflow" / "config"
    assert runtime.debug_directory() == tmp_path / "cineflow" / "debug"


def test_export_directory_environment_wins_over_the_setting(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    root = tmp_path / "cineflow"

    assert runtime.export_directory("/srv/media") == Path("/srv/media").resolve()
    assert runtime.export_directory("exports") == root / "exports"
    monkeypatch.setenv("EXPORT_DIRECTORY", str(tmp_path / "share"))
    assert runtime.export_directory("/srv/media") == tmp_path / "share"
