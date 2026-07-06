"""Generate the binary test fixtures from scratch — no external tools, no
third-party material. Everything below is authored programmatically, so the
repo's audio/image fixtures are CC0 by construction.

Outputs:
    tests/fixtures/audio/cc_sample.opus   1s mono 48kHz Ogg Opus (DTX silence)
    tests/fixtures/audio/cc_sample.mp3    ~0.5s silent MPEG-1 Layer III
    tests/fixtures/cover.png              64x64 solid-color PNG
    src/savesong/assets/cc_sample.opus    bundled copy used by the demo seed

Run: python scripts/gen_fixtures.py  (or `make fixtures`)
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# --- Ogg Opus ----------------------------------------------------------------


def _crc32_ogg(data: bytes) -> int:
    """Ogg page CRC: poly 0x04C11DB7, init 0, not reflected, no final xor."""
    crc = 0
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc


def _ogg_page(
    serial: int,
    seq: int,
    granule: int,
    packets: list[bytes],
    *,
    bos: bool = False,
    eos: bool = False,
) -> bytes:
    segments = bytearray()
    body = bytearray()
    for packet in packets:
        n = len(packet)
        while n >= 255:
            segments.append(255)
            n -= 255
        segments.append(n)
        body += packet
    header_type = (0x02 if bos else 0) | (0x04 if eos else 0)
    header = struct.pack(
        "<4sBBqIIIB", b"OggS", 0, header_type, granule, serial, seq, 0, len(segments)
    ) + bytes(segments)
    page = bytearray(header + bytes(body))
    page[22:26] = struct.pack("<I", _crc32_ogg(bytes(page)))
    return bytes(page)


def _opus_head() -> bytes:
    # version 1, 1 channel, 3840 pre-skip, 48kHz input rate, 0 gain, mapping 0
    return struct.pack("<8sBBHIhB", b"OpusHead", 1, 1, 3840, 48000, 0, 0)


def _opus_tags() -> bytes:
    vendor = b"savesong fixtures"
    comment = b"LICENSE=CC0-1.0"
    return (
        b"OpusTags"
        + struct.pack("<I", len(vendor))
        + vendor
        + struct.pack("<I", 1)
        + struct.pack("<I", len(comment))
        + comment
    )


def make_opus() -> bytes:
    """One second of silence: 50 x 20ms SILK-NB DTX packets (TOC 0x08, empty frame)."""
    serial = 0x53530001
    packets = [b"\x08"] * 50
    granule_end = 3840 + 48000  # pre-skip + 1s of 48kHz samples
    return b"".join(
        [
            _ogg_page(serial, 0, 0, [_opus_head()], bos=True),
            _ogg_page(serial, 1, 0, [_opus_tags()]),
            _ogg_page(serial, 2, granule_end, packets, eos=True),
        ]
    )


# --- MP3 ----------------------------------------------------------------------


def make_mp3(frames: int = 20) -> bytes:
    """Silent MPEG-1 Layer III mono 128kbps 44.1kHz frames (417 bytes each)."""
    header = bytes([0xFF, 0xFB, 0x90, 0xC0])
    frame = header + b"\x00" * (417 - len(header))
    return frame * frames


# --- PNG ----------------------------------------------------------------------


def make_png(rgb: tuple[int, int, int] = (94, 129, 172), size: int = 64) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    raw = (b"\x00" + bytes(rgb) * size) * size
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    opus = make_opus()
    outputs = {
        ROOT / "tests" / "fixtures" / "audio" / "cc_sample.opus": opus,
        ROOT / "tests" / "fixtures" / "audio" / "cc_sample.mp3": make_mp3(),
        ROOT / "tests" / "fixtures" / "cover.png": make_png(),
        ROOT / "src" / "savesong" / "assets" / "cc_sample.opus": opus,
    }
    for path, data in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(f"wrote {path.relative_to(ROOT)} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
