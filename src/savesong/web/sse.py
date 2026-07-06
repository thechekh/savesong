"""Relay pipeline JobProgress events from Redis pub/sub to SSE clients."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from sse_starlette import ServerSentEvent

from savesong.core.library import Library

CHANNEL_PREFIX = "savesong:job:"
TERMINAL_STATES = {"done", "failed", "cancelled"}


def channel_for(job_id: str) -> str:
    return CHANNEL_PREFIX + job_id


def _job_snapshot(state: str, total: int | None, completed: int | None, failed: int | None) -> str:
    return json.dumps(
        {"state": state, "total": total or 0, "completed": completed or 0, "failed": failed or 0}
    )


async def job_events(redis: Any, library: Library, job_id: str) -> AsyncIterator[ServerSentEvent]:
    """Snapshot of the job row first, then live events until ``job_done``."""
    pubsub = redis.pubsub()
    await pubsub.subscribe(channel_for(job_id))
    try:
        row = await library.get_job(job_id)
        if row is not None:
            snapshot = _job_snapshot(row.state, row.total, row.completed, row.failed)
            yield ServerSentEvent(event="state", data=snapshot)
            if row.state in TERMINAL_STATES:
                yield ServerSentEvent(event="job_done", data=snapshot)
                return
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)
            if message is None:
                continue
            raw = message.get("data")
            text = raw.decode("utf-8") if isinstance(raw, bytes | bytearray) else str(raw)
            try:
                event_name = str(json.loads(text).get("event") or "progress")
            except ValueError:
                continue
            yield ServerSentEvent(event=event_name, data=text)
            if event_name == "job_done":
                return
    finally:
        try:
            await pubsub.unsubscribe(channel_for(job_id))
            await pubsub.aclose()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass
