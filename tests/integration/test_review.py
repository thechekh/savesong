"""`savesong review` interactive flow with scripted prompts."""

from __future__ import annotations

import asyncio
import io
import json
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

import savesong.cli.review as review_mod
from savesong.config import Settings
from savesong.core.library import Library
from savesong.core.pipeline import Pipeline
from savesong.models import PlaylistMeta, TrackMeta
from tests.conftest import make_fake_ydl_factory

CANDIDATES = [
    {
        "video_id": "pick0000001",
        "title": "The Right One",
        "channel": "Artist - Topic",
        "duration_s": 200,
        "score": 0.65,
    },
    {
        "video_id": "pick0000002",
        "title": "The Wrong One (Live)",
        "channel": "someone",
        "duration_s": 260,
        "score": 0.41,
    },
]


def console() -> Console:
    return Console(file=io.StringIO(), width=120)


async def _prep(settings: Settings) -> int:
    async with Library(settings.resolved_db_path) as library:
        pid = await library.upsert_playlist(
            PlaylistMeta(source="spotify", external_id="p1", title="P", url="https://x")
        )
        row = await library.upsert_track(
            TrackMeta(
                source="spotify",
                external_id="sp1",
                title="Ambiguous Song",
                artists=["Artist"],
                album="Album",
            ),
            pid,
        )
        await library.mark_needs_review(row.id, 0.65, json.dumps(CANDIDATES))
        return row.id


@pytest.fixture
def review_env(monkeypatch: pytest.MonkeyPatch, sample_opus: Path, fake_fetch: Any) -> None:
    def factory(settings: Any, library: Any, emit: Any = None, **kwargs: Any) -> Pipeline:
        return Pipeline(
            settings,
            library,
            emit=emit,
            ydl_factory=make_fake_ydl_factory(sample_opus),
            fetch=fake_fetch,
        )

    monkeypatch.setattr(review_mod, "_pipeline_factory", factory)


def test_review_nothing_pending(settings: Settings) -> None:
    assert review_mod.run_review(settings, console()) == 0


def test_review_pick_and_download(settings: Settings, review_env: None) -> None:
    row_id = asyncio.run(_prep(settings))
    code = review_mod.run_review(settings, console(), ask=lambda p, c: "1", confirm=lambda p: True)
    assert code == 0

    async def check() -> None:
        async with Library(settings.resolved_db_path) as library:
            row = await library.get_track(row_id)
            assert row is not None
            assert row.status == "done"
            assert row.matched_video_id == "pick0000001"
            assert row.file_path and Path(row.file_path).exists()

    asyncio.run(check())


def test_review_pick_without_download(settings: Settings, review_env: None) -> None:
    row_id = asyncio.run(_prep(settings))
    code = review_mod.run_review(settings, console(), ask=lambda p, c: "1", confirm=lambda p: False)
    assert code == 0

    async def check() -> None:
        async with Library(settings.resolved_db_path) as library:
            row = await library.get_track(row_id)
            assert row is not None
            assert row.status == "matched"
            assert row.file_path is None

    asyncio.run(check())


@pytest.mark.parametrize("answer", ["s", "q"])
def test_review_skip_and_quit_leave_row_untouched(
    settings: Settings, review_env: None, answer: str
) -> None:
    row_id = asyncio.run(_prep(settings))
    code = review_mod.run_review(
        settings, console(), ask=lambda p, c: answer, confirm=lambda p: True
    )
    assert code == 0

    async def check() -> None:
        async with Library(settings.resolved_db_path) as library:
            row = await library.get_track(row_id)
            assert row is not None and row.status == "needs_review"

    asyncio.run(check())
