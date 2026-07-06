"""Async repository over the SQLite library: dedupe, resume, retry, stats, jobs.

One short-lived session per operation — safe to call from concurrent tasks.
Opening the library runs Alembic migrations, so callers never see a stale schema.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from savesong.db.engine import create_db_engine, create_session_factory
from savesong.db.migrate import upgrade_to_head
from savesong.db.tables import JobRow, PlaylistRow, TrackRow
from savesong.models import PlaylistMeta, TrackMeta, TrackStatus


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Library:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._engine: AsyncEngine | None = None
        self._sessions: async_sessionmaker[AsyncSession] | None = None

    async def open(self) -> Library:
        await asyncio.to_thread(upgrade_to_head, self.db_path)
        self._engine = create_db_engine(self.db_path)
        self._sessions = create_session_factory(self._engine)
        await self.reset_stale()
        return self

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
            self._sessions = None

    async def __aenter__(self) -> Library:
        return await self.open()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    def _session(self) -> AsyncSession:
        if self._sessions is None:
            raise RuntimeError("Library is not open — call `await library.open()` first")
        return self._sessions()

    async def reset_stale(self) -> int:
        """Tracks stuck in 'downloading' (crash/cancel) go back to 'pending'."""
        async with self._session() as s, s.begin():
            result = await s.execute(
                update(TrackRow).where(TrackRow.status == "downloading").values(status="pending")
            )
            return int(getattr(result, "rowcount", 0) or 0)

    # -- playlists -----------------------------------------------------------

    async def upsert_playlist(self, meta: PlaylistMeta) -> int:
        async with self._session() as s, s.begin():
            row = (
                await s.execute(
                    select(PlaylistRow).where(
                        PlaylistRow.source == meta.source,
                        PlaylistRow.external_id == meta.external_id,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = PlaylistRow(
                    source=meta.source, external_id=meta.external_id, title=meta.title, url=meta.url
                )
                s.add(row)
                await s.flush()
            else:
                row.title = meta.title
                row.url = meta.url
            return row.id

    async def get_playlist(self, playlist_id: int) -> PlaylistRow | None:
        async with self._session() as s:
            return (
                await s.execute(select(PlaylistRow).where(PlaylistRow.id == playlist_id))
            ).scalar_one_or_none()

    async def playlist_by_external(self, source: str, external_id: str) -> PlaylistRow | None:
        async with self._session() as s:
            return (
                await s.execute(
                    select(PlaylistRow).where(
                        PlaylistRow.source == source, PlaylistRow.external_id == external_id
                    )
                )
            ).scalar_one_or_none()

    async def list_playlists(self) -> list[PlaylistRow]:
        async with self._session() as s:
            return list((await s.execute(select(PlaylistRow).order_by(PlaylistRow.id))).scalars())

    async def touch_playlist_synced(self, playlist_id: int) -> None:
        async with self._session() as s, s.begin():
            await s.execute(
                update(PlaylistRow)
                .where(PlaylistRow.id == playlist_id)
                .values(last_synced_at=utcnow_iso())
            )

    # -- tracks ---------------------------------------------------------------

    async def upsert_track(self, meta: TrackMeta, playlist_id: int | None) -> TrackRow:
        async with self._session() as s, s.begin():
            where = [TrackRow.source == meta.source, TrackRow.external_id == meta.external_id]
            if playlist_id is None:
                where.append(TrackRow.playlist_id.is_(None))
            else:
                where.append(TrackRow.playlist_id == playlist_id)
            row = (await s.execute(select(TrackRow).where(*where))).scalar_one_or_none()
            if row is None:
                row = TrackRow(
                    playlist_id=playlist_id,
                    source=meta.source,
                    external_id=meta.external_id,
                    title=meta.title,
                    artists=json.dumps(meta.artists),
                    album=meta.album,
                    duration_ms=meta.duration_ms,
                    cover_url=meta.cover_url,
                    status="pending",
                )
                s.add(row)
                await s.flush()
            else:
                row.title = meta.title
                row.artists = json.dumps(meta.artists)
                row.album = meta.album
                row.duration_ms = meta.duration_ms
                row.cover_url = meta.cover_url
            return row

    @staticmethod
    def is_downloaded_row(row: TrackRow) -> bool:
        """Dedupe check: recorded as done and the file is still on disk."""
        return row.status == "done" and bool(row.file_path) and Path(str(row.file_path)).exists()

    async def find_done(self, source: str, external_id: str) -> TrackRow | None:
        async with self._session() as s:
            rows = (
                await s.execute(
                    select(TrackRow).where(
                        TrackRow.source == source,
                        TrackRow.external_id == external_id,
                        TrackRow.status == "done",
                    )
                )
            ).scalars()
            for row in rows:
                if self.is_downloaded_row(row):
                    return row
            return None

    async def get_track(self, track_id: int) -> TrackRow | None:
        async with self._session() as s:
            return (
                await s.execute(select(TrackRow).where(TrackRow.id == track_id))
            ).scalar_one_or_none()

    async def set_status(self, track_id: int, status: TrackStatus) -> None:
        async with self._session() as s, s.begin():
            await s.execute(update(TrackRow).where(TrackRow.id == track_id).values(status=status))

    async def mark_downloading(self, track_ids: list[int]) -> None:
        if not track_ids:
            return
        async with self._session() as s, s.begin():
            await s.execute(
                update(TrackRow).where(TrackRow.id.in_(track_ids)).values(status="downloading")
            )

    async def mark_matched(
        self, track_id: int, video_id: str, score: float, candidates_json: str
    ) -> None:
        async with self._session() as s, s.begin():
            await s.execute(
                update(TrackRow)
                .where(TrackRow.id == track_id)
                .values(
                    status="matched",
                    matched_video_id=video_id,
                    match_score=score,
                    match_candidates=candidates_json,
                    error=None,
                )
            )

    async def mark_needs_review(self, track_id: int, score: float, candidates_json: str) -> None:
        async with self._session() as s, s.begin():
            await s.execute(
                update(TrackRow)
                .where(TrackRow.id == track_id)
                .values(status="needs_review", match_score=score, match_candidates=candidates_json)
            )

    async def mark_done(self, track_id: int, file_path: Path) -> None:
        async with self._session() as s, s.begin():
            await s.execute(
                update(TrackRow)
                .where(TrackRow.id == track_id)
                .values(
                    status="done",
                    file_path=str(file_path),
                    downloaded_at=utcnow_iso(),
                    error=None,
                )
            )

    async def mark_failed(self, track_id: int, error: str) -> None:
        async with self._session() as s, s.begin():
            await s.execute(
                update(TrackRow)
                .where(TrackRow.id == track_id)
                .values(status="failed", error=error[:2000])
            )

    async def delete_track(self, track_id: int) -> None:
        async with self._session() as s, s.begin():
            await s.execute(delete(TrackRow).where(TrackRow.id == track_id))

    async def tracks_for_playlist(self, playlist_id: int) -> list[TrackRow]:
        async with self._session() as s:
            return list(
                (
                    await s.execute(
                        select(TrackRow)
                        .where(TrackRow.playlist_id == playlist_id)
                        .order_by(TrackRow.id)
                    )
                ).scalars()
            )

    async def done_tracks_for_playlist(self, playlist_id: int) -> list[TrackRow]:
        return [r for r in await self.tracks_for_playlist(playlist_id) if self.is_downloaded_row(r)]

    async def tracks_by_status(self, status: TrackStatus) -> list[TrackRow]:
        async with self._session() as s:
            return list(
                (
                    await s.execute(
                        select(TrackRow).where(TrackRow.status == status).order_by(TrackRow.id)
                    )
                ).scalars()
            )

    async def failed_tracks(self) -> list[TrackRow]:
        return await self.tracks_by_status("failed")

    async def needs_review_tracks(self) -> list[TrackRow]:
        return await self.tracks_by_status("needs_review")

    async def list_library(
        self, q: str | None = None, cursor: int | None = None, limit: int = 50
    ) -> tuple[list[TrackRow], int | None]:
        """Cursor-paginated done tracks, newest last (stable id order)."""
        async with self._session() as s:
            stmt = select(TrackRow).where(TrackRow.status == "done")
            if q:
                needle = f"%{q}%"
                stmt = stmt.where(
                    or_(
                        TrackRow.title.ilike(needle),
                        TrackRow.artists.ilike(needle),
                        TrackRow.album.ilike(needle),
                    )
                )
            if cursor is not None:
                stmt = stmt.where(TrackRow.id > cursor)
            stmt = stmt.order_by(TrackRow.id).limit(limit + 1)
            rows = list((await s.execute(stmt)).scalars())
            next_cursor = rows[limit - 1].id if len(rows) > limit else None
            return rows[:limit], next_cursor

    async def stats(self) -> dict[str, int]:
        async with self._session() as s:
            by_status = {
                str(status): int(count)
                for status, count in (
                    await s.execute(select(TrackRow.status, func.count()).group_by(TrackRow.status))
                ).all()
            }
            playlists = int((await s.execute(select(func.count(PlaylistRow.id)))).scalar_one())
            tracks = int((await s.execute(select(func.count(TrackRow.id)))).scalar_one())
            return {"playlists": playlists, "tracks": tracks, **by_status}

    # -- jobs (web mode) -------------------------------------------------------

    async def create_job(self, job_id: str, url: str) -> None:
        async with self._session() as s, s.begin():
            s.add(JobRow(id=job_id, url=url, state="queued", created_at=utcnow_iso()))

    async def update_job(self, job_id: str, **fields: Any) -> None:
        async with self._session() as s, s.begin():
            await s.execute(update(JobRow).where(JobRow.id == job_id).values(**fields))

    async def bump_job_counters(self, job_id: str, *, completed: int = 0, failed: int = 0) -> None:
        async with self._session() as s, s.begin():
            await s.execute(
                update(JobRow)
                .where(JobRow.id == job_id)
                .values(
                    completed=func.coalesce(JobRow.completed, 0) + completed,
                    failed=func.coalesce(JobRow.failed, 0) + failed,
                )
            )

    async def get_job(self, job_id: str) -> JobRow | None:
        async with self._session() as s:
            return (await s.execute(select(JobRow).where(JobRow.id == job_id))).scalar_one_or_none()

    async def list_jobs(self, limit: int = 100) -> list[JobRow]:
        async with self._session() as s:
            return list(
                (
                    await s.execute(
                        select(JobRow).order_by(JobRow.created_at.desc(), JobRow.id).limit(limit)
                    )
                ).scalars()
            )
