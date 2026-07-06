"""REST + SSE endpoints (§2.6 of the spec). Single-user, no auth — bind localhost."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from savesong.core.library import Library, utcnow_iso
from savesong.core.resolvers import detect
from savesong.db.tables import JobRow, TrackRow
from savesong.errors import UnsupportedURLError
from savesong.models import AudioFormat
from savesong.web.sse import job_events

router = APIRouter()


class JobCreateRequest(BaseModel):
    url: str
    format: AudioFormat = "opus"


def _library(request: Request) -> Library:
    lib: Library = request.app.state.library
    return lib


def _redis(request: Request) -> Any:
    return request.app.state.redis


def _job_dict(row: JobRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "url": row.url,
        "state": row.state,
        "total": row.total or 0,
        "completed": row.completed or 0,
        "failed": row.failed or 0,
        "created_at": row.created_at,
        "finished_at": row.finished_at,
    }


def _track_dict(row: TrackRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "artists": row.artists_list,
        "album": row.album,
        "status": row.status,
        "match_score": row.match_score,
        "error": row.error,
        "cover_url": row.cover_url,
        "file_path": row.file_path,
        "downloaded_at": row.downloaded_at,
    }


@router.post("/api/jobs", status_code=202)
async def create_job(request: Request, body: JobCreateRequest) -> JSONResponse:
    try:
        detect(body.url)
    except UnsupportedURLError as exc:
        return JSONResponse(
            status_code=422, content={"code": "unsupported_url", "detail": str(exc)}
        )
    job_id = uuid.uuid4().hex
    await _redis(request).enqueue_job("download_job", body.url, body.format, _job_id=job_id)
    await _library(request).create_job(job_id, body.url)
    return JSONResponse(status_code=202, content={"job_id": job_id})


@router.get("/api/jobs")
async def list_jobs(request: Request) -> list[dict[str, Any]]:
    rows = await _library(request).list_jobs()
    return [_job_dict(r) for r in rows]


@router.get("/api/jobs/{job_id}")
async def get_job(request: Request, job_id: str) -> Any:
    library = _library(request)
    row = await library.get_job(job_id)
    if row is None:
        return JSONResponse(status_code=404, content={"code": "job_not_found"})
    tracks: list[TrackRow] = []
    try:
        detected = detect(row.url)
        if detected.kind == "playlist":
            playlist = await library.playlist_by_external(detected.source, detected.external_id)
            if playlist is not None:
                tracks = await library.tracks_for_playlist(playlist.id)
        else:
            # standalone tracks: match on source + external id, newest row wins
            found = await library.find_done(detected.source, detected.external_id)
            if found is not None:
                tracks = [found]
    except UnsupportedURLError:  # pragma: no cover - defensive, urls are validated on create
        tracks = []
    return {**_job_dict(row), "tracks": [_track_dict(t) for t in tracks]}


@router.get("/api/jobs/{job_id}/events")
async def job_event_stream(request: Request, job_id: str) -> EventSourceResponse:
    return EventSourceResponse(job_events(_redis(request), _library(request), job_id), ping=15)


@router.post("/api/jobs/{job_id}/cancel", status_code=202)
async def cancel_job(request: Request, job_id: str) -> Any:
    from arq.jobs import Job

    library = _library(request)
    row = await library.get_job(job_id)
    if row is None:
        return JSONResponse(status_code=404, content={"code": "job_not_found"})
    try:
        await Job(job_id, _redis(request)).abort(timeout=0.5, poll_delay=0.1)
    except Exception:
        # queued-but-never-run jobs have no result to await; 202 either way
        pass
    if row.state in ("queued", "resolving", "running"):
        await library.update_job(job_id, state="cancelled", finished_at=utcnow_iso())
    return JSONResponse(status_code=202, content={"status": "cancelling"})


@router.post("/api/tracks/{track_id}/retry", status_code=202)
async def retry_track(request: Request, track_id: int) -> Any:
    library = _library(request)
    row = await library.get_track(track_id)
    if row is None:
        return JSONResponse(status_code=404, content={"code": "track_not_found"})
    await _redis(request).enqueue_job("retry_track", track_id, _job_id=uuid.uuid4().hex)
    return JSONResponse(status_code=202, content={"status": "queued"})


@router.get("/api/library")
async def library_index(
    request: Request, cursor: int | None = None, q: str | None = None, limit: int = 50
) -> dict[str, Any]:
    rows, next_cursor = await _library(request).list_library(
        q=q, cursor=cursor, limit=min(max(limit, 1), 200)
    )
    return {"items": [_track_dict(r) for r in rows], "next_cursor": next_cursor}


@router.get("/healthz")
async def healthz(request: Request) -> Any:
    redis_ok = True
    try:
        await _redis(request).ping()
    except Exception:
        redis_ok = False
    music_ok = True
    try:
        music_dir = request.app.state.settings.music_dir
        music_dir.mkdir(parents=True, exist_ok=True)
        probe = music_dir / ".savesong-healthz"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError:
        music_ok = False
    if redis_ok and music_ok:
        return {"status": "ok"}
    return JSONResponse(
        status_code=503,
        content={"status": "degraded", "redis": redis_ok, "music_dir": music_ok},
    )
