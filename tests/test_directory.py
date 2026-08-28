"""Directory handler safety and cleanup regression tests."""

from pathlib import Path

import pytest

from cineflow.utils import directory


def handler(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str = "movies") -> directory.DirectoryHandler:
    """Create a handler rooted in a temporary export directory."""
    monkeypatch.setenv("EXPORT_DIRECTORY", str(tmp_path))
    return directory.DirectoryHandler(name)


def test_root_relative_and_nested_directories_are_allowed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert handler(tmp_path, monkeypatch)._path == tmp_path / "movies"
    assert handler(tmp_path, monkeypatch, "movies/trending")._path == tmp_path / "movies" / "trending"


@pytest.mark.parametrize("name", ["../outside", "../../something"])
def test_parent_directory_traversal_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    with pytest.raises(ValueError, match="inside EXPORT_DIRECTORY"):
        handler(tmp_path, monkeypatch, name)


def test_external_absolute_directory_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="inside EXPORT_DIRECTORY"):
        handler(tmp_path, monkeypatch, str(tmp_path.parent / "outside"))


def test_cleanup_removes_expired_item_without_nested_lock_deadlock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = handler(tmp_path, monkeypatch)
    old_item = library._path / "old"
    old_item.mkdir()
    monkeypatch.setattr(directory.time, "time", lambda: old_item.stat().st_ctime + 31 * 24 * 60 * 60)

    library.cleanup()

    assert not old_item.exists()


def test_cleanup_removes_count_excess_without_nested_lock_deadlock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = handler(tmp_path, monkeypatch)
    library.max_item_count = 10
    items = [library._path / f"item-{index}" for index in range(11)]
    for item in items:
        item.mkdir()

    library.cleanup()

    assert len(library.all()) == 10


def test_destructive_item_operation_cannot_escape_library_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = handler(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ValueError, match="inside the configured library"):
        library.remove("../outside")

    assert outside.exists()


def test_directory_handler_has_no_background_worker_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = handler(tmp_path, monkeypatch)

    assert not hasattr(library, "start")
    assert not hasattr(library, "_thread")
