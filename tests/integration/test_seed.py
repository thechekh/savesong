"""Demo seed: 5 CC0 tracks with covers, idempotent."""

from __future__ import annotations

from savesong.config import Settings
from savesong.core.library import Library
from savesong.db.seed import seed, solid_png


async def test_seed_creates_demo_library(settings: Settings) -> None:
    written = await seed(settings)
    assert len(written) == 5
    for path in written:
        assert path.exists()
        assert path.suffix == ".opus"

    from mutagen.oggopus import OggOpus

    tagged = OggOpus(str(written[0]))
    assert tagged["title"] == ["Aurora Drift"]
    assert "metadata_block_picture" in tagged

    async with Library(settings.resolved_db_path) as library:
        rows, _ = await library.list_library()
        assert len(rows) == 5
        assert all((r.cover_url or "").startswith("data:image/png;base64,") for r in rows)
        stats = await library.stats()
        assert stats["playlists"] == 1 and stats["done"] == 5


async def test_seed_is_idempotent(settings: Settings) -> None:
    first = await seed(settings)
    assert len(first) == 5
    second = await seed(settings)
    assert second == []


def test_solid_png_is_valid_png() -> None:
    data = solid_png((10, 20, 30), size=8)
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    assert b"IEND" in data
