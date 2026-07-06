"""FastAPI routes + one full SSE stream, on fakeredis + tmp SQLite."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from savesong.config import Settings
from savesong.core.library import Library
from savesong.models import JobProgress, PlaylistMeta, TrackMeta
from savesong.web.app import create_app
from savesong.web.sse import channel_for

SC_URL = "https://soundcloud.com/dj-orbit/sets/late-night-mix"

WebCtx = tuple[httpx.AsyncClient, Any, Library]


@pytest.fixture
async def web(settings: Settings, arq_redis: Any) -> AsyncIterator[WebCtx]:
    library = await Library(settings.resolved_db_path).open()
    app = create_app(settings, redis=arq_redis, library=library)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, arq_redis, library
    await library.close()


async def test_create_job_enqueues_and_records(web: WebCtx) -> None:
    client, redis, library = web
    resp = await client.post("/api/jobs", json={"url": SC_URL, "format": "opus"})
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    assert await redis.exists(f"arq:job:{job_id}") == 1
    row = await library.get_job(job_id)
    assert row is not None and row.state == "queued" and row.url == SC_URL

    listing = await client.get("/api/jobs")
    assert listing.status_code == 200
    assert [j["id"] for j in listing.json()] == [job_id]


async def test_create_job_rejects_unsupported_url(web: WebCtx) -> None:
    client, _, _ = web
    resp = await client.post("/api/jobs", json={"url": "https://example.com/nope"})
    assert resp.status_code == 422
    assert resp.json()["code"] == "unsupported_url"


async def test_job_detail_includes_playlist_tracks(web: WebCtx, tmp_path: Path) -> None:
    client, _, library = web
    await library.create_job("j1", SC_URL)
    pid = await library.upsert_playlist(
        PlaylistMeta(
            source="soundcloud",
            external_id="dj-orbit/sets/late-night-mix",
            title="Late Night Mix",
            url=SC_URL,
        )
    )
    row = await library.upsert_track(
        TrackMeta(
            source="soundcloud",
            external_id="111",
            title="First Wave",
            artists=["dj-orbit"],
        ),
        pid,
    )
    await library.mark_failed(row.id, "boom")

    resp = await client.get("/api/jobs/j1")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["state"] == "queued"
    assert payload["tracks"] == [
        {
            "id": row.id,
            "title": "First Wave",
            "artists": ["dj-orbit"],
            "album": None,
            "status": "failed",
            "match_score": None,
            "error": "boom",
            "cover_url": None,
            "file_path": None,
            "downloaded_at": None,
        }
    ]


async def test_job_detail_404(web: WebCtx) -> None:
    client, _, _ = web
    assert (await client.get("/api/jobs/missing")).status_code == 404


async def test_sse_stream_snapshot_then_live_events(web: WebCtx) -> None:
    client, redis, library = web
    await library.create_job("jsse", SC_URL)

    async def publish_later() -> None:
        await asyncio.sleep(0.15)
        await redis.publish(
            channel_for("jsse"),
            JobProgress(
                event="progress", title="First Wave", pct=42.0, speed="1.0 MB/s"
            ).model_dump_json(exclude_none=True),
        )
        await redis.publish(
            channel_for("jsse"),
            JobProgress(event="track_done", title="First Wave", status="done").model_dump_json(
                exclude_none=True
            ),
        )
        await redis.publish(
            channel_for("jsse"),
            JobProgress(event="job_done", state="done").model_dump_json(exclude_none=True),
        )

    publisher = asyncio.create_task(publish_later())
    events: list[tuple[str, str]] = []

    async def consume() -> None:
        async with client.stream("GET", "/api/jobs/jsse/events") as resp:
            assert resp.status_code == 200
            current_event = ""
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    current_event = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    events.append((current_event, line.split(":", 1)[1].strip()))

    await asyncio.wait_for(consume(), timeout=10)
    await publisher

    names = [e for e, _ in events]
    assert names[0] == "state"
    assert "progress" in names and "track_done" in names
    assert names[-1] == "job_done"
    progress_payload = json.loads(dict(events)["progress"])
    assert progress_payload["pct"] == 42.0


async def test_sse_terminal_job_closes_immediately(web: WebCtx) -> None:
    client, _, library = web
    await library.create_job("jdone", SC_URL)
    await library.update_job("jdone", state="done", total=3, completed=3)

    names: list[str] = []

    async def consume() -> None:
        async with client.stream("GET", "/api/jobs/jdone/events") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    names.append(line.split(":", 1)[1].strip())

    await asyncio.wait_for(consume(), timeout=5)
    assert names == ["state", "job_done"]


async def test_cancel_job(web: WebCtx) -> None:
    client, _, library = web
    await library.create_job("jcancel", SC_URL)
    resp = await client.post("/api/jobs/jcancel/cancel")
    assert resp.status_code == 202
    row = await library.get_job("jcancel")
    assert row is not None and row.state == "cancelled"
    assert (await client.post("/api/jobs/missing/cancel")).status_code == 404


async def test_retry_track_endpoint(web: WebCtx) -> None:
    client, redis, library = web
    row = await library.upsert_track(
        TrackMeta(source="ytmusic", external_id="vid00000001", title="X", artists=["A"]),
        None,
    )
    await library.mark_failed(row.id, "boom")
    resp = await client.post(f"/api/tracks/{row.id}/retry")
    assert resp.status_code == 202
    assert len(await redis.keys("arq:job:*")) == 1
    assert (await client.post("/api/tracks/99999/retry")).status_code == 404


async def test_library_endpoint_pagination_and_query(web: WebCtx, tmp_path: Path) -> None:
    client, _, library = web
    pid = await library.upsert_playlist(
        PlaylistMeta(source="ytmusic", external_id="p", title="P", url="https://x")
    )
    for i in range(3):
        row = await library.upsert_track(
            TrackMeta(
                source="ytmusic",
                external_id=f"v{i}",
                title=f"Song {i}",
                artists=["Artist"],
                album="Album",
            ),
            pid,
        )
        f = tmp_path / f"{i}.opus"
        f.write_bytes(b"x")
        await library.mark_done(row.id, f)

    page = (await client.get("/api/library", params={"limit": 2})).json()
    assert len(page["items"]) == 2 and page["next_cursor"] is not None
    rest = (
        await client.get("/api/library", params={"limit": 2, "cursor": page["next_cursor"]})
    ).json()
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None

    hits = (await client.get("/api/library", params={"q": "Song 1"})).json()
    assert [i["title"] for i in hits["items"]] == ["Song 1"]
    assert hits["items"][0]["artists"] == ["Artist"]


async def test_healthz_ok(web: WebCtx) -> None:
    client, _, _ = web
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_healthz_degraded_when_music_dir_unwritable(
    settings: Settings, arq_redis: Any, tmp_path: Path
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a directory", encoding="utf-8")
    bad = settings.model_copy(update={"music_dir": blocker})
    library = await Library(bad.resolved_db_path).open()
    app = create_app(bad, redis=arq_redis, library=library)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/healthz")
            assert resp.status_code == 503
            body = resp.json()
            assert body["music_dir"] is False and body["redis"] is True
    await library.close()
