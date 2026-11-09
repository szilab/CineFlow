"""Metadata-only video files built from release names."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cineflow.utils.video import VideoProfile, placeholder_video, release_profile


@pytest.mark.parametrize(("release", "expected"), [
    ("Dune.2024.2160p.UHD.BluRay.REMUX.DV.HDR10.HEVC.TrueHD.Atmos.7.1-FGT",
     VideoProfile(3840, 2160, "hevc", 10, "dv-hdr10", "truehd", 8)),
    ("Show.S01.2160p.ATVP.WEB-DL.DDP5.1.Atmos.DV.H.265-NTb",
     VideoProfile(3840, 2160, "hevc", 10, "dv", "eac3", 6)),
    ("Movie.2023.2160p.WEB-DL.DD+5.1.HDR10+.H.265-FLUX",
     VideoProfile(3840, 2160, "hevc", 10, "hdr10", "eac3", 6)),
    ("Doc.2022.2160p.HLG.x265-GRP", VideoProfile(3840, 2160, "hevc", 10, "hlg")),
    ("Movie.2020.1080p.BluRay.x264.DTS-HD.MA.5.1-GRP",
     VideoProfile(1920, 1080, "h264", 8, "sdr", "dts", 6)),
    ("Anime.2021.1080p.BluRay.10bit.x265.AAC.2.0",
     VideoProfile(1920, 1080, "hevc", 10, "sdr", "aac", 2)),
    ("Movie.2024.720p.WEB.AV1.Opus", VideoProfile(1280, 720, "av1", 8, "sdr")),
    ("Movie.2024.540p.DD5.1", VideoProfile(960, 540, "h264", 8, "sdr", "ac3", 6)),
    ("Movie.2024.HDR.AVC", VideoProfile(1920, 1080, "h264", 10, "hdr10")),
    ("Movie.2024.DoVi.AV1", VideoProfile(1920, 1080, "av1", 10, "hdr10")),
    ("Movie.2024.Dolby.Vision.HDR.x264", VideoProfile(1920, 1080, "h264", 10, "hdr10")),
    ("Movie 2024", VideoProfile()),
    (None, VideoProfile()),
])
def test_release_profile_reads_the_release_name(release, expected) -> None:
    assert release_profile(release) == expected


def test_resolution_argument_wins_over_the_name() -> None:
    assert release_profile("Movie.1080p.x264", "2160p").height == 2160
    assert release_profile("Movie.720p.x264", "N/A").height == 720


@pytest.mark.parametrize("profile", [
    VideoProfile(3840, 2160, "hevc", 10, "dv-hdr10", "truehd", 8),
    VideoProfile(1920, 1080, "hevc", 8, "sdr", "aac", 6),
    VideoProfile(960, 540, "h264", 8, "sdr", "aac", 2),
    VideoProfile(1920, 1080, "h264", 10, "hdr10"),
    VideoProfile(3840, 2160, "av1", 10, "hlg", "eac3", 6),
])
def test_placeholder_video_is_a_small_matroska_header(profile) -> None:
    video = placeholder_video(profile)

    assert video.startswith(bytes.fromhex("1a45dfa3")) and b"matroska" in video
    assert len(video) < 1024
    assert (b"dvcC" in video) == profile.dynamic_range.startswith("dv")


FFPROBE = shutil.which("ffprobe")


@pytest.mark.skipif(FFPROBE is None, reason="ffprobe is not installed")
@pytest.mark.parametrize(("release", "video", "audio"), [
    ("Movie.2160p.DV.HDR10.HEVC.TrueHD.7.1",
     {"codec_name": "hevc", "width": 3840, "height": 2160, "pix_fmt": "yuv420p10le",
      "color_transfer": "smpte2084", "color_primaries": "bt2020"},
     {"codec_name": "truehd", "channels": 8}),
    ("Movie.2160p.HLG.x265", {"codec_name": "hevc", "color_transfer": "arib-std-b67"}, None),
    ("Movie.540p.10bit.x265.AAC.2.0",
     {"codec_name": "hevc", "width": 960, "height": 540, "pix_fmt": "yuv420p10le"},
     {"codec_name": "aac", "channels": 2}),
    ("Movie.1080p.x264.DD5.1", {"codec_name": "h264", "width": 1920, "height": 1080,
                                "color_transfer": "bt709"}, {"codec_name": "ac3", "channels": 6}),
    ("Movie.2160p.HDR.AV1.DDP5.1",
     {"codec_name": "av1", "width": 3840, "height": 2160, "pix_fmt": "yuv420p10le",
      "color_transfer": "smpte2084"}, {"codec_name": "eac3", "channels": 6}),
])
def test_ffprobe_reads_the_release_properties(tmp_path: Path, release, video, audio) -> None:
    """Media servers read the streams with ffprobe; the header alone must describe them."""
    path = tmp_path / "video.mkv"
    path.write_bytes(placeholder_video(release_profile(release)))

    result = subprocess.run(
        [FFPROBE, "-v", "quiet", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True, check=True, text=True, timeout=30,
    )
    streams = json.loads(result.stdout)["streams"]

    assert {key: streams[0].get(key) for key in video} == video
    if audio:
        assert {key: streams[1].get(key) for key in audio} == audio
    else:
        assert len(streams) == 1
    if "DV" in release:
        assert streams[0]["side_data_list"][0]["dv_profile"] == 8
