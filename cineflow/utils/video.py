"""Build metadata-only video files from release names.

A library item needs a video file so media servers list it. Instead of copying
a real video, CineFlow writes a tiny Matroska file that holds no pictures, only
the stream headers: resolution, video codec with a valid parameter set, bit
depth, HDR signalling (HDR10, HLG, Dolby Vision) and the audio track, as far as
the release name tells them. Media servers read these headers with ffprobe, so
the item shows the properties of the release. The file cannot be played.
"""

import re
import struct
from dataclasses import dataclass

RESOLUTIONS = {
    '360p': (640, 360), '480p': (854, 480), '540p': (960, 540), '576p': (1024, 576),
    '720p': (1280, 720), '1080p': (1920, 1080), '1440p': (2560, 1440),
    '2160p': (3840, 2160), '4320p': (7680, 4320),
}
DEFAULT_RESOLUTION = '1080p'

# colour primaries, transfer characteristics and matrix coefficients (ITU-T H.273)
SDR_COLOUR = (1, 1, 1)
PQ_COLOUR = (9, 16, 9)
HLG_COLOUR = (9, 18, 9)

AUDIO_CHANNELS = {'truehd': 8, 'dts': 6, 'eac3': 6, 'ac3': 6, 'aac': 2}
AUDIO_CODEC_IDS = {
    'truehd': 'A_TRUEHD', 'dts': 'A_DTS', 'eac3': 'A_EAC3', 'ac3': 'A_AC3', 'aac': 'A_AAC',
}
AAC_CHANNEL_CONFIG = {1: 1, 2: 2, 6: 6, 8: 7}


@dataclass(frozen=True)
class VideoProfile:
    """Stream properties of a release."""

    width: int = 1920
    height: int = 1080
    codec: str = 'h264'          # h264, hevc or av1
    bit_depth: int = 8           # 8 or 10
    dynamic_range: str = 'sdr'   # sdr, hdr10, hlg, dv or dv-hdr10
    audio: str | None = None     # truehd, dts, eac3, ac3, aac or None
    channels: int = 0


# the first matching pattern wins
DYNAMIC_RANGE_PATTERNS = (
    ('dv', r'(?<![a-z])(dv|dovi)(?![a-z])|dolby[ ._-]?vision'),
    ('hdr10', r'(?<![a-z])hdr(10)?(\+|plus)?(?![a-z])'),
    ('hlg', r'(?<![a-z])hlg(?![a-z])'),
)
CODEC_PATTERNS = (
    ('av1', r'(?<![a-z0-9])av1(?![a-z0-9])'),
    ('hevc', r'(?<![a-z0-9])(x265|h[ .]?265|hevc)(?![a-z0-9])'),
    ('h264', r'(?<![a-z0-9])(x264|h[ .]?264|avc)(?![a-z0-9])'),
)
AUDIO_PATTERNS = (
    ('truehd', r'true[ ._-]?hd'),
    ('dts', r'(?<![a-z])dts'),
    ('eac3', r'(?<![a-z])(ddp|dd\+|e-?ac-?3)|atmos'),
    ('ac3', r'(?<![a-z])(dd|ac-?3)(?![a-z+])'),
    ('aac', r'(?<![a-z])aac'),
)
TEN_BIT_PATTERN = r'(?<![a-z0-9])(10[ ._-]?bits?|hi10p?)(?![a-z0-9])'
CHANNEL_PATTERN = r'(?<![0-9])([1257])[ .]([01])(?![0-9])'


def _first(patterns: tuple, text: str) -> str | None:
    """Return the key of the first pattern found in the text."""
    return next((key for key, pattern in patterns if re.search(pattern, text)), None)


def _dynamic_range(name: str, codec: str | None) -> str:
    """Return sdr, hdr10, hlg, dv (Dolby Vision only) or dv-hdr10."""
    found = _first(DYNAMIC_RANGE_PATTERNS, name) or 'sdr'
    if found != 'dv':
        return found
    if codec not in (None, 'hevc'):
        # the Dolby Vision record is only written for HEVC; keep the PQ signal
        return 'hdr10'
    return 'dv-hdr10' if _first(DYNAMIC_RANGE_PATTERNS[1:2], name) else 'dv'


def release_profile(release: str | None, resolution: str | None = None) -> VideoProfile:
    """Return the stream properties that a release name states.

    ``resolution`` (for example ``2160p``) wins over the name; without either
    the profile is 1080p. Properties the name does not state get common values.
    """
    name = str(release or '').lower()
    resolution = (resolution or '').lower()
    if resolution not in RESOLUTIONS:
        resolution = next((key for key in RESOLUTIONS if key in name), DEFAULT_RESOLUTION)
    width, height = RESOLUTIONS[resolution]

    stated_codec = _first(CODEC_PATTERNS, name)
    dynamic_range = _dynamic_range(name, stated_codec)
    codec = stated_codec or ('h264' if dynamic_range == 'sdr' else 'hevc')
    bit_depth = 10 if re.search(TEN_BIT_PATTERN, name) or dynamic_range != 'sdr' else 8

    audio = _first(AUDIO_PATTERNS, name)
    channels = 0
    if audio:
        layout = re.search(CHANNEL_PATTERN, name)
        channels = int(layout.group(1)) + int(layout.group(2)) if layout else AUDIO_CHANNELS[audio]
    return VideoProfile(
        width=width, height=height, codec=codec, bit_depth=bit_depth,
        dynamic_range=dynamic_range, audio=audio, channels=channels,
    )


class _Bits:
    """Write the bit fields of a video parameter set."""

    def __init__(self) -> None:
        self._bits: list[int] = []

    def u(self, width: int, value: int) -> '_Bits':
        self._bits.extend((value >> shift) & 1 for shift in range(width - 1, -1, -1))
        return self

    def ue(self, value: int) -> '_Bits':
        value += 1
        return self.u(value.bit_length() - 1, 0).u(value.bit_length(), value)

    def se(self, value: int) -> '_Bits':
        return self.ue(2 * value - 1 if value > 0 else -2 * value)

    def trailing(self) -> bytes:
        self._bits.append(1)
        self._bits.extend([0] * (-len(self._bits) % 8))
        return bytes(
            int(''.join(map(str, self._bits[index:index + 8])), 2)
            for index in range(0, len(self._bits), 8)
        )


def _nal(header: bytes, payload: bytes) -> bytes:
    """Return a NAL unit with emulation prevention bytes."""
    out = bytearray(header)
    zeros = 0
    for byte in payload:
        if zeros >= 2 and byte <= 3:
            out.append(3)
            zeros = 0
        out.append(byte)
        zeros = zeros + 1 if byte == 0 else 0
    return bytes(out)


def _colour(profile: VideoProfile) -> tuple[int, int, int]:
    if profile.dynamic_range == 'hlg':
        return HLG_COLOUR
    if profile.dynamic_range != 'sdr':
        return PQ_COLOUR
    return SDR_COLOUR


def _padding(size: int, block: int) -> int:
    return -size % block


def _hevc_level(height: int) -> int:
    return 93 if height <= 720 else 123 if height <= 1080 else 153 if height <= 2160 else 183


def _hevc_profile_tier_level(bits: _Bits, profile_idc: int, level: int) -> None:
    bits.u(2, 0).u(1, 0).u(5, profile_idc)
    bits.u(32, (1 << (31 - profile_idc)) | (1 << 29 if profile_idc == 1 else 0))
    bits.u(1, 1).u(1, 0).u(1, 0).u(1, 1).u(43, 0).u(1, 0)
    bits.u(8, level)


def _hevc_config(profile: VideoProfile) -> bytes:
    """Return the HEVCDecoderConfigurationRecord with VPS, SPS and PPS."""
    profile_idc = 2 if profile.bit_depth == 10 else 1
    level = _hevc_level(profile.height)
    depth = profile.bit_depth - 8

    vps = _Bits().u(4, 0).u(1, 1).u(1, 1).u(6, 0).u(3, 0).u(1, 1).u(16, 0xFFFF)
    _hevc_profile_tier_level(vps, profile_idc, level)
    vps.u(1, 1).ue(4).ue(0).ue(0).u(6, 0).ue(0).u(1, 0).u(1, 0)

    pad_w, pad_h = _padding(profile.width, 8), _padding(profile.height, 8)
    sps = _Bits().u(4, 0).u(3, 0).u(1, 1)
    _hevc_profile_tier_level(sps, profile_idc, level)
    sps.ue(0).ue(1).ue(profile.width + pad_w).ue(profile.height + pad_h)
    if pad_w or pad_h:
        sps.u(1, 1).ue(0).ue(pad_w // 2).ue(0).ue(pad_h // 2)
    else:
        sps.u(1, 0)
    sps.ue(depth).ue(depth).ue(4).u(1, 1).ue(4).ue(0).ue(0)
    sps.ue(0).ue(3).ue(0).ue(3).ue(1).ue(1)
    sps.u(1, 0).u(1, 0).u(1, 0).u(1, 0).ue(0).u(1, 0).u(1, 0).u(1, 0)
    primaries, transfer, matrix = _colour(profile)
    sps.u(1, 1).u(1, 0).u(1, 0).u(1, 1).u(3, 5).u(1, 0).u(1, 1)
    sps.u(8, primaries).u(8, transfer).u(8, matrix)
    sps.u(1, 0).u(1, 0).u(1, 0).u(1, 0).u(1, 0).u(1, 0).u(1, 0).u(1, 0)

    pps = _Bits().ue(0).ue(0).u(1, 0).u(1, 0).u(3, 0).u(1, 0).u(1, 0).ue(0).ue(0).se(0)
    pps.u(1, 0).u(1, 0).u(1, 0).se(0).se(0).u(1, 0).u(1, 0).u(1, 0).u(1, 0).u(1, 0)
    pps.u(1, 0).u(1, 0).u(1, 0).u(1, 0).u(1, 0).ue(0).u(1, 0).u(1, 0)

    units = (
        (32, _nal(bytes((32 << 1, 1)), vps.trailing())),
        (33, _nal(bytes((33 << 1, 1)), sps.trailing())),
        (34, _nal(bytes((34 << 1, 1)), pps.trailing())),
    )
    record = bytearray((1, profile_idc))
    record += struct.pack('>I', (1 << (31 - profile_idc)) | (1 << 29 if profile_idc == 1 else 0))
    record += bytes((0x90, 0, 0, 0, 0, 0, level))
    record += bytes((0xF0, 0x00, 0xFC, 0xFD, 0xF8 | depth, 0xF8 | depth, 0, 0, 0x0F, len(units)))
    for nal_type, unit in units:
        record += bytes((0x80 | nal_type,)) + struct.pack('>HH', 1, len(unit)) + unit
    return bytes(record)


def _avc_config(profile: VideoProfile) -> bytes:
    """Return the AVCDecoderConfigurationRecord with SPS and PPS."""
    profile_idc = 110 if profile.bit_depth == 10 else 100
    height = profile.height
    level = 31 if height <= 720 else 41 if height <= 1080 else 51 if height <= 2160 else 60
    depth = profile.bit_depth - 8
    pad_w, pad_h = _padding(profile.width, 16), _padding(profile.height, 16)

    sps = _Bits().u(8, profile_idc).u(8, 0).u(8, level).ue(0)
    sps.ue(1).ue(depth).ue(depth).u(1, 0).u(1, 0)
    sps.ue(0).ue(2).ue(1).u(1, 0)
    sps.ue((profile.width + pad_w) // 16 - 1).ue((profile.height + pad_h) // 16 - 1)
    sps.u(1, 1).u(1, 1)
    if pad_w or pad_h:
        sps.u(1, 1).ue(0).ue(pad_w // 2).ue(0).ue(pad_h // 2)
    else:
        sps.u(1, 0)
    primaries, transfer, matrix = _colour(profile)
    sps.u(1, 1).u(1, 0).u(1, 0).u(1, 1).u(3, 5).u(1, 0).u(1, 1)
    sps.u(8, primaries).u(8, transfer).u(8, matrix)
    sps.u(1, 0).u(1, 0).u(1, 0).u(1, 0).u(1, 0).u(1, 0)
    pps = _Bits().ue(0).ue(0).u(1, 1).u(1, 0).ue(0).ue(0).ue(0).u(1, 0).u(2, 0)
    pps.se(0).se(0).se(0).u(1, 1).u(1, 0).u(1, 0)

    sps_unit = _nal(b'\x67', sps.trailing())
    pps_unit = _nal(b'\x68', pps.trailing())
    record = bytes((1, profile_idc, 0, level, 0xFF, 0xE1)) + struct.pack('>H', len(sps_unit)) + sps_unit
    record += bytes((1,)) + struct.pack('>H', len(pps_unit)) + pps_unit
    return record + bytes((0xFD, 0xF8 | depth, 0xF8 | depth, 0))


def _leb128(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _av1_config(profile: VideoProfile) -> bytes:
    """Return the AV1CodecConfigurationRecord with a sequence header."""
    height = profile.height
    level = 5 if height <= 720 else 8 if height <= 1080 else 12 if height <= 2160 else 16
    high_bitdepth = int(profile.bit_depth == 10)
    primaries, transfer, matrix = _colour(profile)
    header = _Bits().u(3, 0).u(1, 0).u(1, 0).u(1, 0).u(1, 0).u(5, 0).u(12, 0).u(5, level)
    if level > 7:
        header.u(1, 0)
    header.u(4, 15).u(4, 15).u(16, profile.width - 1).u(16, profile.height - 1)
    header.u(1, 0).u(1, 0).u(1, 0).u(1, 0).u(1, 0).u(1, 0).u(1, 0).u(1, 0).u(1, 0)
    header.u(1, 1).u(1, 1).u(1, 0).u(1, 0).u(1, 0)
    header.u(1, high_bitdepth).u(1, 0).u(1, 1).u(8, primaries).u(8, transfer).u(8, matrix)
    header.u(1, 0).u(2, 0).u(1, 0).u(1, 0)
    payload = header.trailing()
    obu = bytes((0x0A,)) + _leb128(len(payload)) + payload
    return bytes((0x81, level, 0x0C | (high_bitdepth << 6), 0)) + obu


def _dolby_vision_config(profile: VideoProfile) -> bytes:
    """Return the dvcC record: profile 8.1 with an HDR10 base layer, else profile 5."""
    dv_profile, compatibility = (8, 1) if profile.dynamic_range == 'dv-hdr10' else (5, 0)
    dv_level = 6 if profile.height > 1080 else 4
    flags = (dv_profile << 9) | (dv_level << 3) | 0b101
    return bytes((1, 0)) + struct.pack('>H', flags) + bytes((compatibility << 4,)) + bytes(19)


def _ebml(element_id: int, data) -> bytes:
    """Return one EBML element."""
    if isinstance(data, int):
        data = data.to_bytes(max(1, (data.bit_length() + 7) // 8), 'big')
    elif isinstance(data, float):
        data = struct.pack('>d', data)
    elif isinstance(data, str):
        data = data.encode()
    size = len(data)
    length = next(n for n in range(1, 9) if size < (1 << (7 * n)) - 1)
    return element_id.to_bytes((element_id.bit_length() + 7) // 8, 'big') + \
        (size | (1 << (7 * length))).to_bytes(length, 'big') + data


def _audio_track(profile: VideoProfile) -> bytes:
    entry = _ebml(0xD7, 2) + _ebml(0x73C5, 2) + _ebml(0x83, 2)
    entry += _ebml(0x86, AUDIO_CODEC_IDS[profile.audio]) + _ebml(0x22B59C, 'und')
    if profile.audio == 'aac':
        config = AAC_CHANNEL_CONFIG.get(profile.channels, 2)
        entry += _ebml(0x63A2, struct.pack('>H', (2 << 11) | (3 << 7) | (config << 3)))
    entry += _ebml(0xE1, _ebml(0xB5, 48000.0) + _ebml(0x9F, profile.channels))
    return _ebml(0xAE, entry)


def placeholder_video(profile: VideoProfile) -> bytes:
    """Return a Matroska file that only describes the streams of the profile."""
    codecs = {
        'hevc': ('V_MPEGH/ISO/HEVC', _hevc_config),
        'h264': ('V_MPEG4/ISO/AVC', _avc_config),
        'av1': ('V_AV1', _av1_config),
    }
    codec_id, config = codecs[profile.codec]
    primaries, transfer, matrix = _colour(profile)
    colour = _ebml(0x55B0, _ebml(0x55B1, matrix) + _ebml(0x55B2, profile.bit_depth) + _ebml(0x55B9, 1)
                   + _ebml(0x55BA, transfer) + _ebml(0x55BB, primaries))
    video = _ebml(0xE0, _ebml(0xB0, profile.width) + _ebml(0xBA, profile.height) + colour)
    entry = _ebml(0xD7, 1) + _ebml(0x73C5, 1) + _ebml(0x83, 1) + _ebml(0x86, codec_id)
    entry += _ebml(0x63A2, config(profile)) + video
    if profile.dynamic_range.startswith('dv'):
        entry += _ebml(0x41E4, _ebml(0x41E7, int.from_bytes(b'dvcC', 'big'))
                       + _ebml(0x41ED, _dolby_vision_config(profile)))
    tracks = _ebml(0xAE, entry)
    if profile.audio:
        tracks += _audio_track(profile)

    header = _ebml(0x1A45DFA3, _ebml(0x4286, 1) + _ebml(0x42F7, 1) + _ebml(0x42F2, 4)
                   + _ebml(0x42F3, 8) + _ebml(0x4282, 'matroska') + _ebml(0x4287, 4)
                   + _ebml(0x4285, 2))
    info = _ebml(0x1549A966, _ebml(0x2AD7B1, 1000000) + _ebml(0x4D80, 'CineFlow')
                 + _ebml(0x5741, 'CineFlow'))
    cluster = _ebml(0x1F43B675, _ebml(0xE7, 0))
    return header + _ebml(0x18538067, info + _ebml(0x1654AE6B, tracks) + cluster)
