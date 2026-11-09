"""Directory handler safety and cleanup regression tests."""

import os
import time
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
    with pytest.raises(ValueError, match="inside the export directory"):
        handler(tmp_path, monkeypatch, name)


def test_external_absolute_directory_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="inside the export directory"):
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


def test_publish_creates_a_complete_item_before_it_becomes_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = handler(tmp_path, monkeypatch)
    item = "Film (2026) [tmdbid-7]"
    media = {"title": "Film", "year": 2026, "tmdbid": 7}

    assert library.publish(item=item, media=media)

    item_path = library._path / item
    assert library.imprt(item) == media
    assert (item_path / "Film.mkv").exists()
    assert library.all() == [item_path]


def test_publish_recovers_an_interrupted_existing_item_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = handler(tmp_path, monkeypatch)
    item = "Film (2026) [tmdbid-7]"
    original = {"title": "Film", "year": 2026, "torrent": "old"}
    replacement = {"title": "Film", "year": 2026, "torrent": "new"}
    assert library.publish(item=item, media=original)
    item_path = library._path / item
    real_replace = directory.os.replace

    def fail_staged_publish(source, destination):
        if Path(source).name.startswith(library.STAGE_PREFIX) and Path(destination) == item_path:
            raise OSError("simulated interruption")
        return real_replace(source, destination)

    monkeypatch.setattr(directory.os, "replace", fail_staged_publish)
    assert not library.publish(item=item, media=replacement)
    assert not item_path.exists()
    monkeypatch.setattr(directory.os, "replace", real_replace)

    recovered = handler(tmp_path, monkeypatch)

    assert recovered.imprt(item) == replacement
    assert not list(recovered._path.glob(f"{recovered.TRANSACTION_PREFIX}*"))
    assert not list(recovered._path.glob(f"{recovered.BACKUP_PREFIX}*"))
    assert not list(recovered._path.glob(f"{recovered.STAGE_PREFIX}*"))


def test_remove_hides_item_before_a_failed_permanent_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = handler(tmp_path, monkeypatch)
    item = "Film (2026) [tmdbid-7]"
    assert library.publish(item=item, media={"title": "Film", "year": 2026})
    monkeypatch.setattr(directory.shutil, "rmtree", lambda _path: (_ for _ in ()).throw(OSError("busy")))

    assert not library.remove(item)
    assert not (library._path / item).exists()
    assert library.all() == []
    assert len(list((library._path / library.TRASH_DIRECTORY).iterdir())) == 1
    library.cleanup()
    assert len(list((library._path / library.TRASH_DIRECTORY).iterdir())) == 1


def test_directory_handler_has_no_background_worker_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = handler(tmp_path, monkeypatch)

    assert not hasattr(library, "start")
    assert not hasattr(library, "_thread")


def test_handlers_of_the_same_directory_share_one_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = handler(tmp_path, monkeypatch)
    second = handler(tmp_path, monkeypatch)
    other = handler(tmp_path, monkeypatch, "series")

    assert first._lock is second._lock
    assert first._lock is not other._lock


def test_cleaner_waits_one_period_before_cleaning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup never deletes items; the first cleanup happens after the delay."""
    cleaned = []
    cleaner = directory.DirectoryCleaner(handler(tmp_path, monkeypatch))
    cleaner.handler = type("Fake", (), {"cleanup": lambda self: cleaned.append(True)})()
    waits = iter([False, True])
    monkeypatch.setattr(cleaner._stop_event, "wait", lambda timeout: next(waits))
    cleaner._running = True

    cleaner.worker()

    assert cleaned == [True]


def test_cleaner_survives_cleanup_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cleaner = directory.DirectoryCleaner(handler(tmp_path, monkeypatch))

    def failing_cleanup():
        raise OSError("disk")

    cleaner.handler = type("Fake", (), {"cleanup": lambda self: failing_cleanup()})()
    waits = iter([False, False, True])
    monkeypatch.setattr(cleaner._stop_event, "wait", lambda timeout: next(waits))
    cleaner._running = True

    cleaner.worker()


def test_published_video_carries_the_publish_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Jellyfin sorts "Date added" by the video timestamps, so each publish must stamp its own time."""
    library = handler(tmp_path / "export", monkeypatch)
    item = "Film (2026) [tmdbid-7]"
    before = time.time() - 1

    assert library.publish(item=item, media={"title": "Film", "year": 2026}, resolution="1080p")

    assert (library._path / item / "Film.mkv").stat().st_mtime >= before


def test_published_video_describes_the_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The video file is a small Matroska header built from the release name, not a copied sample."""
    library = handler(tmp_path / "export", monkeypatch)
    item = "Film (2026) [tmdbid-7]"
    media = {"title": "Film", "year": 2026, "torrent": "Film.2026.2160p.WEB-DL.DDP5.1.HDR.H.265-GRP"}

    assert library.publish(item=item, media=media, resolution="2160p")

    video = (library._path / item / "Film.mkv").read_bytes()
    assert video.startswith(bytes.fromhex("1a45dfa3"))
    assert len(video) < 1024
    assert b"V_MPEGH/ISO/HEVC" in video and b"A_EAC3" in video


def test_upgraded_release_gets_a_newer_video_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Replacing an item changes the video mtime, which makes Jellyfin re-read "Date added"."""
    library = handler(tmp_path / "export", monkeypatch)
    item = "Film (2026) [tmdbid-7]"
    media = {"title": "Film", "year": 2026}
    assert library.publish(item=item, media={**media, "torrent": "Film.1080p"}, resolution="1080p")
    video = library._path / item / "Film.mkv"
    os.utime(video, (1_600_000_000, 1_600_000_000))

    assert library.publish(item=item, media={**media, "torrent": "Film.1080p.HUN"}, resolution="1080p")

    assert video.stat().st_mtime > 1_600_000_000
