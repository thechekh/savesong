"""arq task definitions: JobProgress → Redis pub/sub → SSE, jobs table updates."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from savesong.config import Settings
from savesong.core.library import Library, utcnow_iso
from savesong.core.pipeline import Pipeline
from savesong.errors import SaveSongError
from savesong.models import AudioFormat, JobProgress, JobState
from savesong.web.sse import channel_for


async def _publisher(
    redis: Any, library: Library, job_id: str, queue: asyncio.Queue[JobProgress | None]
) -> None:
    """Single consumer: publish events to pub/sub and mirror them into the jobs row."""
    channel = channel_for(job_id)
    while True:
        event = await queue.get()
        if event is None:
            return
        event.job_id = job_id
        try:
            await redis.publish(channel, event.model_dump_json(exclude_none=True))
        except Exception:  # pragma: no cover - pub/sub is best-effort
            pass
        if event.event == "state" and event.state is not None:
            fields: dict[str, Any] = {"state": event.state}
            if event.total is not None:
                fields["total"] = event.total
            await library.update_job(job_id, **fields)
        elif event.event == "track_done":
            if event.status in ("done", "skipped"):
                await library.bump_job_counters(job_id, completed=1)
            elif event.status == "failed":
                await library.bump_job_counters(job_id, failed=1)


async def _open_library(ctx: dict[str, Any], settings: Settings) -> tuple[Library, bool]:
    injected = ctx.get("library")
    if injected is not None:
        return cast(Library, injected), False
    return await Library(settings.resolved_db_path).open(), True


async def download_job(ctx: dict[str, Any], url: str, fmt: str) -> str:
    """Resolve + download ``url``; the whole pipeline streams progress to SSE."""
    job_id = str(ctx.get("job_id"))
    redis = ctx["redis"]
    settings = cast(Settings, ctx.get("settings") or Settings())
    library, owns_library = await _open_library(ctx, settings)

    queue: asyncio.Queue[JobProgress | None] = asyncio.Queue()
    publisher = asyncio.create_task(_publisher(redis, library, job_id, queue))
    pipeline = Pipeline(settings, library, emit=queue.put_nowait, **ctx.get("pipeline_kwargs", {}))

    final: JobState = "done"
    try:
        summary = await pipeline.run_url(url, fmt=cast(AudioFormat, fmt))
        if summary.failed and not summary.downloaded and not summary.skipped:
            final = "failed"
        return final
    except asyncio.CancelledError:
        final = "cancelled"
        queue.put_nowait(JobProgress(event="job_done", state="cancelled"))
        raise
    except SaveSongError as exc:
        final = "failed"
        queue.put_nowait(JobProgress(event="job_done", state="failed", error=str(exc)))
        return "failed"
    finally:
        # drain queued events first so a stale 'state' event can't overwrite
        # the terminal state written below
        queue.put_nowait(None)
        try:
            await asyncio.wait_for(publisher, timeout=10)
        except (TimeoutError, asyncio.CancelledError):  # pragma: no cover - defensive
            publisher.cancel()
        await library.update_job(job_id, state=final, finished_at=utcnow_iso())
        await pipeline.aclose()
        if owns_library:
            await library.close()


async def retry_track(ctx: dict[str, Any], track_id: int) -> str:
    """Re-download a single library row (used by POST /api/tracks/{id}/retry)."""
    settings = cast(Settings, ctx.get("settings") or Settings())
    library, owns_library = await _open_library(ctx, settings)
    pipeline = Pipeline(settings, library, **ctx.get("pipeline_kwargs", {}))
    try:
        row = await library.get_track(track_id)
        if row is None:
            return "missing"
        summary = await pipeline.download_rows([row])
        return "done" if summary.downloaded else "failed"
    finally:
        await pipeline.aclose()
        if owns_library:
            await library.close()
