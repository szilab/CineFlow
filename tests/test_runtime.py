"""Runtime path and first-run configuration behavior."""

from pathlib import Path

from cineflow import runtime


def test_cineflow_home_supplies_default_layout(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CFG_DIRECTORY", raising=False)
    monkeypatch.delenv("EXPORT_DIRECTORY", raising=False)
    monkeypatch.delenv("MEDIA_DIRECTORY", raising=False)
    monkeypatch.setenv("CINEFLOW_HOME", str(tmp_path))

    assert runtime.application_root() == tmp_path
    assert runtime.config_directory() == tmp_path / "config"
    assert runtime.export_directory() == tmp_path / "library"
    assert runtime.media_directory() == tmp_path / "media"


def test_explicit_directories_override_cineflow_home(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    configured = {name: tmp_path / name.lower() for name in (
        "CFG_DIRECTORY", "EXPORT_DIRECTORY", "MEDIA_DIRECTORY"
    )}
    monkeypatch.setenv("CINEFLOW_HOME", str(home))
    for name, path in configured.items():
        monkeypatch.setenv(name, str(path))

    assert runtime.config_directory() == configured["CFG_DIRECTORY"]
    assert runtime.export_directory() == configured["EXPORT_DIRECTORY"]
    assert runtime.media_directory() == configured["MEDIA_DIRECTORY"]


def test_frozen_executable_directory_is_application_root(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("CINEFLOW_HOME", raising=False)
    monkeypatch.setattr(runtime.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime.sys, "executable", str(tmp_path / "CineFlow.exe"))

    assert runtime.application_root() == tmp_path


def test_bootstrap_copies_all_examples_into_empty_directory(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "config"
    examples = tmp_path / "examples"
    examples.mkdir()
    for filename in ("config.yaml", "from_lib.yaml", "to_lib.yaml"):
        (examples / filename).write_text(f"source: {filename}\n", encoding="utf-8")
    monkeypatch.setenv("CFG_DIRECTORY", str(destination))
    monkeypatch.setattr(runtime, "bundled_examples_directory", lambda: examples)

    copied = runtime.bootstrap_configuration()

    assert {path.name for path in copied} == {"config.yaml", "from_lib.yaml", "to_lib.yaml"}
    assert (destination / "from_lib.yaml").read_text(encoding="utf-8") == "source: from_lib.yaml\n"


def test_bootstrap_never_overwrites_nonempty_configuration(tmp_path, monkeypatch) -> None:
    destination = tmp_path / "config"
    destination.mkdir()
    existing = destination / "config.yaml"
    existing.write_text("user: configuration\n", encoding="utf-8")
    monkeypatch.setenv("CFG_DIRECTORY", str(destination))
    monkeypatch.setattr(
        runtime, "bundled_examples_directory", lambda: Path("examples-that-must-not-be-read")
    )

    assert runtime.bootstrap_configuration() == ()
    assert existing.read_text(encoding="utf-8") == "user: configuration\n"
