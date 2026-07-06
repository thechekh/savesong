"""Seed demo library rows: 5 tracks pointing at the bundled CC0 clip + covers.

Lets a fresh `docker compose up` show a populated Library tab with zero
downloads and zero API keys. Idempotent — re-running skips existing files.
"""

from __future__ import annotations

import asyncio
import base64
import struct
import zlib
from importlib.resources import files
from pathlib import Path

from savesong.config import Settings
from savesong.core import organizer
from savesong.core.library import Library
from savesong.core.tagger import tag_file
from savesong.models import PlaylistMeta, TrackMeta

# (title, artist, album, year, cover RGB) — invented demo metadata.
DEMO_TRACKS: list[tuple[str, str, str, int, tuple[int, int, int]]] = [
    ("Aurora Drift", "Lumen Fields", "Demo Mixtape", 2024, (94, 129, 172)),
    ("Paper Planets", "Casio Tide", "Demo Mixtape", 2023, (163, 190, 140)),
    ("Night Bus Home", "Velvet Static", "Demo Mixtape", 2025, (180, 142, 173)),
    ("Glass Harbor", "Marble Arcade", "Demo Mixtape", 2022, (208, 135, 112)),
    ("Sunday Renderer", "Pixel Foliage", "Demo Mixtape", 2024, (235, 203, 139)),
]


def solid_png(rgb: tuple[int, int, int], size: int = 96) -> bytes:
    """Tiny solid-color PNG, generated without any imaging dependency."""

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


def png_data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def bundled_sample() -> bytes:
    """The CC0 Ogg Opus clip shipped inside the package."""
    return files("savesong").joinpath("assets", "cc_sample.opus").read_bytes()


async def seed(settings: Settings | None = None) -> list[Path]:
    s = settings or Settings()
    sample = bundled_sample()
    written: list[Path] = []
    async with Library(s.resolved_db_path) as library:
        playlist = PlaylistMeta(
            source="ytmusic",
            external_id="demo-mixtape",
            title="Demo Mixtape (seeded)",
            url="https://example.invalid/demo-mixtape",
        )
        playlist_id = await library.upsert_playlist(playlist)
        for i, (title, artist, album, year, rgb) in enumerate(DEMO_TRACKS, 1):
            cover = solid_png(rgb)
            meta = TrackMeta(
                source="ytmusic",
                external_id=f"demo-{i:03d}",
                title=title,
                artists=[artist],
                album=album,
                duration_ms=1000,
                track_number=i,
                release_year=year,
                cover_url=png_data_uri(cover),
            )
            row = await library.upsert_track(meta, playlist_id)
            if Library.is_downloaded_row(row):
                continue
            dest = organizer.build_track_path(s.music_dir, artist, album, i, title, "opus")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(sample)
            tag_file(dest, meta, cover=cover, cover_mime="image/png")
            await library.mark_done(row.id, dest)
            written.append(dest)
    return written


def main() -> None:
    written = asyncio.run(seed())
    if written:
        print(f"seeded {len(written)} demo tracks:")
        for path in written:
            print(f"  {path}")
    else:
        print("demo library already seeded — nothing to do")


if __name__ == "__main__":
    main()
