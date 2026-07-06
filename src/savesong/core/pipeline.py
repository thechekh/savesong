"""Pipeline: resolve → match → download → convert → tag → record → export.

This is the single orchestrator both frontends drive; the CLI and web layers
only render the :class:`JobProgress` events it emits. Every collaborator
(yt-dlp factory, YT Music search, cover fetcher, resolvers) is injectable so
the whole pipeline runs offline in tests.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

import httpx

from savesong.config import Settings
from savesong.core import matcher, organizer
from savesong.core.downloader import DownloadEngine, DownloadRequest, YdlFactory
from savesong.core.library import Library
from savesong.core.m3u import write_m3u8
from savesong.core.resolvers import (
    Resolver,
    SoundCloudResolver,
    SpotifyResolver,
    YTMusicResolver,
    detect,
)
from savesong.core.resolvers.detect import DetectedURL
from savesong.core.resolvers.ytmusic import search_candidates
from savesong.db.tables import TrackRow
from savesong.errors import SaveSongError
from savesong.models import (
    AudioFormat,
    DownloadResult,
    JobProgress,
    MatchCandidate,
    MatchResult,
    Resolved,
    Source,
    Summary,
    TrackMeta,
    TrackStatus,
)

EmitFn = Callable[[JobProgress], None]
SearchFn = Callable[[str], Awaitable[list[MatchCandidate]]]
FetchFn = Callable[[str], Awaitable[tuple[bytes, str] | None]]


def watch_url(video_id: str) -> str:
    return f"https://music.youtube.com/watch?v={video_id}"


async def default_fetch_bytes(url: str) -> tuple[bytes, str] | None:  # pragma: no cover - network
    """Fetch cover art; returns (bytes, mime) or None on any failure."""
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(url)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200 or not resp.content:
        return None
    mime = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip() or "image/jpeg"
    return resp.content, mime


def row_to_meta(row: TrackRow) -> TrackMeta:
    return TrackMeta(
        source=cast(Source, row.source),
        external_id=row.external_id,
        title=row.title,
        artists=row.artists_list,
        album=row.album,
        duration_ms=row.duration_ms,
        cover_url=row.cover_url,
    )


def row_media_url(row: TrackRow) -> str | None:
    """Reconstruct a yt-dlp-able URL from a library row (used by retry/review)."""
    if row.source == "spotify":
        return watch_url(str(row.matched_video_id)) if row.matched_video_id else None
    if row.source == "ytmusic":
        return watch_url(row.external_id)
    if row.external_id.isdigit():
        return f"https://api.soundcloud.com/tracks/{row.external_id}"
    return f"https://soundcloud.com/{row.external_id}"


def _candidates_json(result: MatchResult | None) -> str:
    return json.dumps(
        [
            {
                "video_id": sc.candidate.video_id,
                "title": sc.candidate.title,
                "channel": sc.candidate.channel,
                "duration_s": sc.candidate.duration_s,
                "score": round(sc.score, 4),
            }
            for sc in (result.top if result else [])
        ]
    )


class Pipeline:
    def __init__(
        self,
        settings: Settings,
        library: Library,
        *,
        emit: EmitFn | None = None,
        ydl_factory: YdlFactory | None = None,
        search: SearchFn | None = None,
        fetch: FetchFn | None = None,
        resolvers: dict[str, Resolver] | None = None,
    ) -> None:
        self.settings = settings
        self.library = library
        self._emit_fn = emit
        self._ydl_factory = ydl_factory
        self._search_fn: SearchFn = search or (lambda q: search_candidates(q))
        self._fetch = fetch or default_fetch_bytes
        self._resolvers: dict[str, Resolver] = dict(resolvers or {})
        self._engine: DownloadEngine | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._rows: dict[str, TrackRow] = {}
        self._summary = Summary()
        self._last_playlist_id: int | None = None

    # -- lifecycle -------------------------------------------------------------

    def cancel(self) -> None:
        if self._engine is not None:
            self._engine.cancel()

    async def aclose(self) -> None:
        for resolver in self._resolvers.values():
            await resolver.aclose()

    def _resolver_for(self, source: Source) -> Resolver:
        if source not in self._resolvers:
            if source == "spotify":
                self._resolvers[source] = SpotifyResolver(
                    self.settings.spotify_client_id, self.settings.spotify_client_secret
                )
            elif source == "soundcloud":
                self._resolvers[source] = SoundCloudResolver()
            else:
                self._resolvers[source] = YTMusicResolver()
        return self._resolvers[source]

    # -- events ------------------------------------------------------------------

    def _emit(self, event: JobProgress) -> None:
        if self._emit_fn is not None:
            self._emit_fn(event)

    def _progress_from_thread(self, external_id: str, pct: float, speed: str | None) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._emit_progress, external_id, pct, speed)

    def _emit_progress(self, external_id: str, pct: float, speed: str | None) -> None:
        row = self._rows.get(external_id)
        self._emit(
            JobProgress(
                event="progress",
                track_id=row.id if row else None,
                external_id=external_id,
                title=row.title if row else external_id,
                pct=round(pct, 1),
                speed=speed,
            )
        )

    def _emit_track_done(
        self, row: TrackRow | None, meta: TrackMeta, status: TrackStatus, error: str | None = None
    ) -> None:
        self._emit(
            JobProgress(
                event="track_done",
                track_id=row.id if row else None,
                external_id=meta.external_id,
                title=meta.title,
                status=status,
                error=error,
            )
        )

    # -- public API ---------------------------------------------------------------

    async def dry_run(self, url: str) -> list[DownloadResult]:
        """Resolve + match only; nothing is downloaded or persisted."""
        detected, resolved = await self._resolve(url)
        results: list[DownloadResult] = []
        for meta in resolved.tracks:
            if await self.library.find_done(meta.source, meta.external_id):
                results.append(DownloadResult(track=meta, status="skipped"))
                continue
            if detected.source != "spotify":
                results.append(DownloadResult(track=meta, status="matched"))
                continue
            candidates = await self._search_fn(f"{meta.artist} {meta.title}")
            match = matcher.pick(meta, candidates, self.settings.match_threshold)
            status: TrackStatus = "needs_review" if match.needs_review else "matched"
            results.append(DownloadResult(track=meta, status=status, match=match))
        return results

    async def run_url(self, url: str, *, fmt: AudioFormat | None = None) -> Summary:
        self._loop = asyncio.get_running_loop()
        fmt = fmt or self.settings.format
        detected, resolved = await self._resolve(url)

        playlist_id: int | None = None
        if resolved.playlist is not None:
            playlist_id = await self.library.upsert_playlist(resolved.playlist)
        self._last_playlist_id = playlist_id

        rows: list[tuple[TrackMeta, TrackRow]] = []
        for meta in resolved.tracks:
            row = await self.library.upsert_track(meta, playlist_id)
            self._rows[meta.external_id] = row
            rows.append((meta, row))

        summary = Summary(
            playlist_title=resolved.playlist.title if resolved.playlist else None,
            total=len(rows),
        )
        self._summary = summary
        self._emit(JobProgress(event="state", state="running", total=len(rows)))

        pending: list[tuple[TrackMeta, TrackRow]] = []
        for meta, row in rows:
            if Library.is_downloaded_row(row):
                summary.skipped += 1
                summary.results.append(
                    DownloadResult(
                        track=meta,
                        status="skipped",
                        file_path=Path(str(row.file_path)) if row.file_path else None,
                    )
                )
                self._emit_track_done(row, meta, "skipped")
            else:
                pending.append((meta, row))

        downloads = await self._plan_downloads(detected, pending, summary)
        requests = self._build_requests(resolved, downloads, fmt)
        if requests:
            await self.library.mark_downloading([row.id for _, row, _ in downloads])
            await self._download(requests)

        await self._finalize_playlist(resolved, playlist_id, summary)
        self._emit(JobProgress(event="job_done", state="done", summary=summary))
        return summary

    async def sync_url(
        self, url: str, *, fmt: AudioFormat | None = None, prune: bool = False
    ) -> tuple[Summary, list[TrackRow]]:
        """`get` + report tracks that vanished from the source playlist."""
        summary = await self.run_url(url, fmt=fmt)
        removed: list[TrackRow] = []
        if self._last_playlist_id is not None:
            current_ids = set(self._rows.keys())
            for row in await self.library.tracks_for_playlist(self._last_playlist_id):
                if row.external_id not in current_ids:
                    removed.append(row)
                    if prune:
                        if row.file_path:
                            Path(str(row.file_path)).unlink(missing_ok=True)
                        await self.library.delete_track(row.id)
        return summary, removed

    async def retry_failed(self, *, fmt: AudioFormat | None = None) -> Summary:
        rows = await self.library.failed_tracks()
        return await self.download_rows(rows, fmt=fmt)

    async def download_rows(
        self, rows: list[TrackRow], *, fmt: AudioFormat | None = None
    ) -> Summary:
        """Download specific library rows (retry-failed, review picks)."""
        self._loop = asyncio.get_running_loop()
        fmt = fmt or self.settings.format
        summary = Summary(total=len(rows))
        self._summary = summary
        self._emit(JobProgress(event="state", state="running", total=len(rows)))
        requests: list[DownloadRequest] = []
        planned: set[Path] = set()
        for row in rows:
            meta = row_to_meta(row)
            self._rows[meta.external_id] = row
            media = await self._ensure_media(row, meta)
            if media is None:
                summary.needs_review += 1
                summary.results.append(DownloadResult(track=meta, status="needs_review"))
                self._emit_track_done(row, meta, "needs_review")
                continue
            dest = organizer.build_track_path(
                self.settings.music_dir,
                meta.artist,
                meta.album or "Singles",
                None,
                meta.title,
                fmt,
                exists=lambda p: p.exists() or p in planned,
            )
            planned.add(dest)
            requests.append(DownloadRequest(track=meta, media_url=media, dest=dest, fmt=fmt))
        if requests:
            await self.library.mark_downloading(
                [self._rows[r.track.external_id].id for r in requests]
            )
            await self._download(requests)
        self._emit(JobProgress(event="job_done", state="done", summary=summary))
        return summary

    # -- internals ------------------------------------------------------------------

    async def _resolve(self, url: str) -> tuple[DetectedURL, Resolved]:
        detected = detect(url)
        self._emit(JobProgress(event="state", state="resolving"))
        resolver = self._resolver_for(detected.source)
        resolved = await resolver.resolve(detected.url)
        return detected, resolved

    async def _ensure_media(self, row: TrackRow, meta: TrackMeta) -> str | None:
        """Media URL for a row; spotify rows without a stored match get re-matched."""
        media = row_media_url(row)
        if media is not None or row.source != "spotify":
            return media
        candidates = await self._search_fn(f"{meta.artist} {meta.title}")
        match = matcher.pick(meta, candidates, self.settings.match_threshold)
        if match.needs_review or match.best is None:
            await self.library.mark_needs_review(row.id, match.score, _candidates_json(match))
            return None
        await self.library.mark_matched(
            row.id, match.best.video_id, match.score, _candidates_json(match)
        )
        return watch_url(match.best.video_id)

    async def _plan_downloads(
        self,
        detected: DetectedURL,
        pending: list[tuple[TrackMeta, TrackRow]],
        summary: Summary,
    ) -> list[tuple[TrackMeta, TrackRow, str]]:
        """Match (spotify) or pass through (direct sources) → media URLs."""
        downloads: list[tuple[TrackMeta, TrackRow, str]] = []
        if detected.source != "spotify":
            for meta, row in pending:
                if meta.url:
                    downloads.append((meta, row, meta.url))
                else:
                    await self.library.mark_failed(row.id, "no media URL from extractor")
                    summary.failed += 1
                    summary.results.append(
                        DownloadResult(track=meta, status="failed", error="no media URL")
                    )
                    self._emit_track_done(row, meta, "failed", "no media URL")
            return downloads

        matches: dict[str, MatchResult | None] = {}
        errors: dict[str, str] = {}
        sem = asyncio.Semaphore(self.settings.concurrency)

        async def match_one(meta: TrackMeta, row: TrackRow) -> None:
            async with sem:
                if row.matched_video_id and row.status in ("matched", "failed", "downloading"):
                    matches[meta.external_id] = MatchResult(
                        best=MatchCandidate(video_id=str(row.matched_video_id), title=meta.title),
                        score=row.match_score or 1.0,
                        needs_review=False,
                        top=[],
                    )
                    return
                try:
                    candidates = await self._search_fn(f"{meta.artist} {meta.title}")
                except SaveSongError as exc:
                    errors[meta.external_id] = str(exc)
                    matches[meta.external_id] = None
                    return
                matches[meta.external_id] = matcher.pick(
                    meta, candidates, self.settings.match_threshold
                )

        async with asyncio.TaskGroup() as tg:
            for meta, row in pending:
                tg.create_task(match_one(meta, row))

        for meta, row in pending:
            match = matches.get(meta.external_id)
            if match is None:
                error = errors.get(meta.external_id, "search failed")
                await self.library.mark_failed(row.id, error)
                summary.failed += 1
                summary.results.append(DownloadResult(track=meta, status="failed", error=error))
                self._emit_track_done(row, meta, "failed", error)
                continue
            if match.needs_review or match.best is None:
                await self.library.mark_needs_review(row.id, match.score, _candidates_json(match))
                summary.needs_review += 1
                summary.results.append(
                    DownloadResult(track=meta, status="needs_review", match=match)
                )
                self._emit_track_done(row, meta, "needs_review")
                continue
            await self.library.mark_matched(
                row.id, match.best.video_id, match.score, _candidates_json(match)
            )
            downloads.append((meta, row, watch_url(match.best.video_id)))
        return downloads

    def _build_requests(
        self,
        resolved: Resolved,
        downloads: list[tuple[TrackMeta, TrackRow, str]],
        fmt: AudioFormat,
    ) -> list[DownloadRequest]:
        planned: set[Path] = set()
        requests: list[DownloadRequest] = []
        for i, (meta, _row, media) in enumerate(downloads, 1):
            collection = meta.album or (resolved.playlist.title if resolved.playlist else "Singles")
            index = meta.track_number
            if index is None and resolved.playlist is not None:
                index = i
            dest = organizer.build_track_path(
                self.settings.music_dir,
                meta.artist,
                collection,
                index,
                meta.title,
                fmt,
                exists=lambda p: p.exists() or p in planned,
            )
            planned.add(dest)
            requests.append(DownloadRequest(track=meta, media_url=media, dest=dest, fmt=fmt))
        return requests

    async def _download(self, requests: list[DownloadRequest]) -> None:
        engine = DownloadEngine(
            concurrency=self.settings.concurrency,
            ydl_factory=self._ydl_factory,
            on_progress=self._progress_from_thread,
            on_result=self._handle_result,
        )
        self._engine = engine
        await engine.run(requests)

    async def _handle_result(self, result: DownloadResult) -> None:
        summary = self._summary
        row = self._rows.get(result.track.external_id)
        if result.status == "done" and result.file_path is not None:
            await self._tag(result)
            if row is not None:
                await self.library.mark_done(row.id, result.file_path)
            summary.downloaded += 1
            summary.results.append(result)
            self._emit_track_done(row, result.track, "done")
        elif result.status == "failed":
            if row is not None:
                await self.library.mark_failed(row.id, result.error or "download failed")
            summary.failed += 1
            summary.results.append(result)
            self._emit_track_done(row, result.track, "failed", result.error)
        else:
            # cancelled mid-flight — leave for the next run to resume
            if row is not None:
                await self.library.set_status(row.id, "pending")

    async def _tag(self, result: DownloadResult) -> None:
        assert result.file_path is not None
        cover: tuple[bytes, str] | None = None
        if result.track.cover_url:
            cover = await self._fetch(result.track.cover_url)
        try:
            await asyncio.to_thread(
                _tag_sync,
                result.file_path,
                result.track,
                cover[0] if cover else None,
                cover[1] if cover else "image/jpeg",
            )
        except Exception as exc:
            result.error = f"tagged with errors: {exc}"

    async def _finalize_playlist(
        self, resolved: Resolved, playlist_id: int | None, summary: Summary
    ) -> None:
        if resolved.playlist is None or playlist_id is None:
            return
        done_rows = await self.library.done_tracks_for_playlist(playlist_id)
        if done_rows:
            entries = [(Path(str(r.file_path)), row_to_meta(r)) for r in done_rows if r.file_path]
            m3u_path = self.settings.music_dir / (
                organizer.sanitize_component(resolved.playlist.title) + ".m3u8"
            )
            await asyncio.to_thread(write_m3u8, m3u_path, entries)
            summary.m3u_path = m3u_path
        await self.library.touch_playlist_synced(playlist_id)


def _tag_sync(path: Path, track: TrackMeta, cover: bytes | None, mime: str) -> None:
    from savesong.core.tagger import tag_file

    tag_file(path, track, cover, mime)
