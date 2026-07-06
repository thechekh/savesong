"""SQLAlchemy ORM tables (schema mirrored in the initial Alembic migration)."""

from __future__ import annotations

import json

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SOURCES_SQL = "source IN ('spotify','soundcloud','ytmusic')"
TRACK_STATUSES_SQL = (
    "status IN ('pending','matched','downloading','done','failed','needs_review','skipped')"
)
JOB_STATES_SQL = "state IN ('queued','resolving','running','done','failed','cancelled')"


class Base(DeclarativeBase):
    pass


class PlaylistRow(Base):
    __tablename__ = "playlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str]
    external_id: Mapped[str]
    title: Mapped[str]
    url: Mapped[str]
    last_synced_at: Mapped[str | None]

    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_playlists_source_external_id"),
        CheckConstraint(SOURCES_SQL, name="ck_playlists_source"),
    )


class TrackRow(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(primary_key=True)
    playlist_id: Mapped[int | None] = mapped_column(ForeignKey("playlists.id"))
    source: Mapped[str]
    external_id: Mapped[str]
    title: Mapped[str]
    artists: Mapped[str]
    """JSON array of artist names."""
    album: Mapped[str | None]
    duration_ms: Mapped[int | None]
    cover_url: Mapped[str | None]
    status: Mapped[str] = mapped_column(default="pending", server_default="pending")
    matched_video_id: Mapped[str | None]
    match_score: Mapped[float | None]
    match_candidates: Mapped[str | None]
    """JSON top-3 candidates for `savesong review`."""
    file_path: Mapped[str | None]
    error: Mapped[str | None]
    downloaded_at: Mapped[str | None]

    __table_args__ = (
        UniqueConstraint(
            "source", "external_id", "playlist_id", name="uq_tracks_source_external_playlist"
        ),
        CheckConstraint(TRACK_STATUSES_SQL, name="ck_tracks_status"),
        Index("tracks_status", "status"),
    )

    @property
    def artists_list(self) -> list[str]:
        try:
            parsed = json.loads(self.artists)
        except (TypeError, ValueError):
            return [self.artists] if self.artists else []
        if isinstance(parsed, list):
            return [str(a) for a in parsed]
        return [str(parsed)]


class JobRow(Base):
    """Web-mode job bookkeeping (id is the arq job id)."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(primary_key=True)
    url: Mapped[str]
    state: Mapped[str] = mapped_column(default="queued", server_default="queued")
    total: Mapped[int | None] = mapped_column(default=0, server_default="0")
    completed: Mapped[int | None] = mapped_column(default=0, server_default="0")
    failed: Mapped[int | None] = mapped_column(default=0, server_default="0")
    created_at: Mapped[str]
    finished_at: Mapped[str | None]

    __table_args__ = (CheckConstraint(JOB_STATES_SQL, name="ck_jobs_state"),)
