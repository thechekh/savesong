"""Download engine: staging/atomic rename, concurrency bound, cancellation."""

from __future__ import annotations

import asyncio
from pathlib import Path

from savesong.core.downloader import DownloadEngine, DownloadRequest
from savesong.models import DownloadResult, TrackMeta
from tests.conftest import ConcurrencyProbe, make_fake_ydl_factory


def req(tmp_path: Path, vid: str, fmt: str = "opus") -> DownloadRequest:
    track = TrackMeta(source="ytmusic", external_id=vid, title=f"Track {vid}", artists=["A"])
    return DownloadRequest(
        track=track,
        media_url=f"https://music.youtube.com/watch?v={vid}",
        dest=tmp_path / "music" / "A" / "Album" / f"{vid}.{fmt}",
        fmt="opus",
    )


def no_part_dirs(root: Path) -> bool:
    return not [p for p in root.rglob(".part-*")]


async def test_download_success_atomic(tmp_path: Path, sample_opus: Path) -> None:
    progress: list[tuple[str, float]] = []
    engine = DownloadEngine(
        concurrency=2,
        ydl_factory=make_fake_ydl_factory(sample_opus),
        on_progress=lambda ext_id, pct, speed: progress.append((ext_id, pct)),
    )
    request = req(tmp_path, "vid00000001")
    results = await engine.run([request])

    assert [r.status for r in results] == ["done"]
    assert results[0].file_path == request.dest
    assert request.dest.exists()
    assert request.dest.read_bytes() == sample_opus.read_bytes()
    assert no_part_dirs(tmp_path)
    pcts = [p for _, p in progress]
    assert pcts == sorted(pcts) and pcts[-1] == 100.0


async def test_download_failure_reported(tmp_path: Path, sample_opus: Path) -> None:
    engine = DownloadEngine(
        concurrency=2,
        ydl_factory=make_fake_ydl_factory(sample_opus, fail_ids=frozenset({"bad00000001"})),
    )
    good, bad = req(tmp_path, "ok000000001"), req(tmp_path, "bad00000001")
    results = await engine.run([good, bad])
    by_id = {r.track.external_id: r for r in results}
    assert by_id["ok000000001"].status == "done"
    assert by_id["bad00000001"].status == "failed"
    assert "simulated download failure" in (by_id["bad00000001"].error or "")
    assert not bad.dest.exists()
    assert no_part_dirs(tmp_path)


async def test_concurrency_bounded(tmp_path: Path, sample_opus: Path) -> None:
    probe = ConcurrencyProbe()
    engine = DownloadEngine(
        concurrency=3,
        ydl_factory=make_fake_ydl_factory(sample_opus, delay=0.02, probe=probe),
    )
    requests = [req(tmp_path, f"vid{i:08d}") for i in range(9)]
    results = await engine.run(requests)
    assert all(r.status == "done" for r in results)
    assert probe.max_seen <= 3


async def test_cancel_leaves_no_partials(tmp_path: Path, sample_opus: Path) -> None:
    engine = DownloadEngine(
        concurrency=2,
        ydl_factory=make_fake_ydl_factory(sample_opus, delay=0.05),
    )
    requests = [req(tmp_path, f"vid{i:08d}") for i in range(6)]
    task = asyncio.create_task(engine.run(requests))
    await asyncio.sleep(0.08)
    engine.cancel()
    results = await task

    assert engine.cancelled
    statuses = {r.status for r in results}
    assert "pending" in statuses  # at least some were aborted
    assert no_part_dirs(tmp_path)
    for r in results:
        if r.status == "pending":
            assert not (r.file_path and r.file_path.exists())


async def test_on_result_streams_completions(tmp_path: Path, sample_opus: Path) -> None:
    seen: list[str] = []

    async def on_result(result: DownloadResult) -> None:
        seen.append(result.track.external_id)

    engine = DownloadEngine(
        concurrency=2,
        ydl_factory=make_fake_ydl_factory(sample_opus),
        on_result=on_result,
    )
    requests = [req(tmp_path, f"vid{i:08d}") for i in range(3)]
    await engine.run(requests)
    assert sorted(seen) == sorted(r.track.external_id for r in requests)
