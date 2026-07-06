"""arq worker in burst mode against fakeredis, running the real job functions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from arq.worker import Worker, func

from savesong.config import Settings
from savesong.core.library import Library
from savesong.core.resolvers.soundcloud import SoundCloudResolver
from savesong.web.jobs import download_job, retry_track
from tests.conftest import make_fake_ydl_factory
from tests.integration.test_resolvers_ytdlp import SC_SET

SC_URL = "https://soundcloud.com/dj-orbit/sets/late-night-mix"


@pytest.fixture(autouse=True)
def _quiet_arq(monkeypatch: pytest.MonkeyPatch) -> None:
    """fakeredis lacks INFO; skip arq's startup redis-info banner."""

    async def noop(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr("arq.worker.log_redis_info", noop)


async def sc_extract(url: str) -> dict[str, Any]:
    return SC_SET


def make_worker(redis: Any, ctx: dict[str, Any]) -> Worker:
    return Worker(
        functions=[func(download_job, name="download_job"), func(retry_track, name="retry_track")],
        redis_pool=redis,
        burst=True,
        poll_delay=0.02,
        handle_signals=False,
        allow_abort_jobs=True,
        ctx=ctx,
    )


def pipeline_kwargs(sample_opus: Path, fake_fetch: Any) -> dict[str, Any]:
    return {
        "ydl_factory": make_fake_ydl_factory(sample_opus),
        "fetch": fake_fetch,
        "resolvers": {"soundcloud": SoundCloudResolver(extract=sc_extract)},
    }


async def test_worker_runs_download_job(
    settings: Settings, arq_redis: Any, sample_opus: Path, fake_fetch: Any
) -> None:
    library = await Library(settings.resolved_db_path).open()
    try:
        ctx = {
            "settings": settings,
            "library": library,
            "pipeline_kwargs": pipeline_kwargs(sample_opus, fake_fetch),
        }
        await arq_redis.enqueue_job("download_job", SC_URL, "opus", _job_id="wjob1")
        await library.create_job("wjob1", SC_URL)

        await make_worker(arq_redis, ctx).main()

        row = await library.get_job("wjob1")
        assert row is not None
        assert row.state == "done"
        assert row.total == 2 and row.completed == 2 and row.failed == 0
        assert row.finished_at is not None
        stats = await library.stats()
        assert stats["done"] == 2
        files = list(settings.music_dir.rglob("*.opus"))
        assert len(files) == 2
    finally:
        await library.close()


async def test_worker_marks_job_failed_on_resolve_error(
    settings: Settings, arq_redis: Any, sample_opus: Path, fake_fetch: Any
) -> None:
    library = await Library(settings.resolved_db_path).open()
    try:
        ctx = {
            "settings": settings,
            "library": library,
            "pipeline_kwargs": pipeline_kwargs(sample_opus, fake_fetch),
        }
        # spotify URL with no credentials configured → SpotifyAuthError inside the job
        url = "https://open.spotify.com/playlist/5FpYt2XoNbXvJp0k4v3Kx1"
        await arq_redis.enqueue_job("download_job", url, "opus", _job_id="wjob2")
        await library.create_job("wjob2", url)

        await make_worker(arq_redis, ctx).main()

        row = await library.get_job("wjob2")
        assert row is not None and row.state == "failed"
    finally:
        await library.close()


async def test_worker_retry_track(
    settings: Settings, arq_redis: Any, sample_opus: Path, fake_fetch: Any
) -> None:
    from savesong.models import TrackMeta

    library = await Library(settings.resolved_db_path).open()
    try:
        row = await library.upsert_track(
            TrackMeta(
                source="ytmusic",
                external_id="vid00000042",
                title="Comeback",
                artists=["A"],
                album="Album",
            ),
            None,
        )
        await library.mark_failed(row.id, "flaky network")
        ctx = {
            "settings": settings,
            "library": library,
            "pipeline_kwargs": pipeline_kwargs(sample_opus, fake_fetch),
        }
        await arq_redis.enqueue_job("retry_track", row.id, _job_id="wjob3")

        await make_worker(arq_redis, ctx).main()

        refreshed = await library.get_track(row.id)
        assert refreshed is not None and refreshed.status == "done"
        assert refreshed.file_path and Path(refreshed.file_path).exists()
    finally:
        await library.close()
