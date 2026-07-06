"""Typed data models shared by the core engine, CLI, and web frontends."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["spotify", "soundcloud", "ytmusic"]
AudioFormat = Literal["opus", "m4a", "mp3"]
TrackStatus = Literal[
    "pending", "matched", "downloading", "done", "failed", "needs_review", "skipped"
]
JobState = Literal["queued", "resolving", "running", "done", "failed", "cancelled"]

AUDIO_FORMATS: tuple[AudioFormat, ...] = ("opus", "m4a", "mp3")


class TrackMeta(BaseModel):
    """Normalized track metadata, independent of which source produced it."""

    source: Source
    external_id: str
    title: str
    artists: list[str] = Field(default_factory=list)
    album: str | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    cover_url: str | None = None
    track_number: int | None = None
    release_year: int | None = None
    url: str | None = None
    """Direct page URL usable by yt-dlp (SoundCloud/YT Music); None for Spotify."""

    @property
    def artist(self) -> str:
        return self.artists[0] if self.artists else "Unknown Artist"

    @property
    def artist_display(self) -> str:
        return ", ".join(self.artists) if self.artists else "Unknown Artist"


class PlaylistMeta(BaseModel):
    source: Source
    external_id: str
    title: str
    url: str
    tracks: list[TrackMeta] = Field(default_factory=list)


class Resolved(BaseModel):
    """Result of resolving a URL: a playlist, or a single standalone track."""

    playlist: PlaylistMeta | None = None
    tracks: list[TrackMeta] = Field(default_factory=list)

    @property
    def is_playlist(self) -> bool:
        return self.playlist is not None


class MatchCandidate(BaseModel):
    """A YouTube Music search result considered as the audio source for a track."""

    video_id: str
    title: str
    channel: str = ""
    duration_s: int | None = None
    view_count: int | None = None


class ScoredCandidate(BaseModel):
    candidate: MatchCandidate
    score: float


class MatchResult(BaseModel):
    """Outcome of scoring candidates for one track (see docs/matching.md)."""

    best: MatchCandidate | None = None
    score: float = 0.0
    needs_review: bool = True
    top: list[ScoredCandidate] = Field(default_factory=list)
    """Top-3 scored candidates, best first — persisted for `savesong review`."""


class DownloadResult(BaseModel):
    track: TrackMeta
    status: TrackStatus
    file_path: Path | None = None
    error: str | None = None
    match: MatchResult | None = None


class Summary(BaseModel):
    """Final tally for one `get`/`sync` run."""

    playlist_title: str | None = None
    total: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    needs_review: int = 0
    results: list[DownloadResult] = Field(default_factory=list)
    m3u_path: Path | None = None


class JobProgress(BaseModel):
    """Progress event emitted by the pipeline.

    The CLI renders these with Rich; web mode publishes them to Redis pub/sub
    where they are relayed as SSE events named after ``event``.
    """

    event: Literal["state", "progress", "track_done", "job_done"]
    job_id: str | None = None
    state: JobState | None = None
    total: int | None = None
    track_id: int | None = None
    external_id: str | None = None
    title: str | None = None
    pct: float | None = None
    speed: str | None = None
    status: TrackStatus | None = None
    error: str | None = None
    summary: Summary | None = None
