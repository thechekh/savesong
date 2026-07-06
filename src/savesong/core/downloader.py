"""Bounded-concurrency async download engine over yt-dlp.

All yt-dlp interaction is isolated behind this module (plus the thin
``extract_info_async`` helper the resolvers share), so upstream API drift
touches one seam. yt-dlp itself is synchronous; each download runs in a
worker thread via :func:`asyncio.to_thread`.

Files are downloaded into a ``.part-*`` staging directory next to their final
destination and atomically renamed into place, so cancellation (Ctrl-C, arq
abort) never leaves partial files behind.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from savesong.core import converter
from savesong.errors import DownloadCancelled, DownloadFailed
from savesong.models import AudioFormat, DownloadResult, TrackMeta

ProgressCallback = Callable[[str, float, str | None], None]
"""(track external_id, pct 0..100, human-readable speed or None)."""

ResultCallback = Callable[[DownloadResult], Awaitable[None]]


class YDLProto(Protocol):
    """The slice of ``yt_dlp.YoutubeDL`` the engine relies on (test seam)."""

    def __enter__(self) -> YDLProto: ...

    def __exit__(self, *exc: object) -> None: ...

    def extract_info(self, url: str, download: bool = True) -> dict[str, Any] | None: ...


YdlFactory = Callable[[dict[str, Any]], YDLProto]


def default_ydl_factory(opts: dict[str, Any]) -> YDLProto:  # pragma: no cover - network path
    import yt_dlp

    ydl: YDLProto = yt_dlp.YoutubeDL(opts)
    return ydl


async def extract_info_async(url: str, *, flat: bool = True) -> dict[str, Any]:
    """Metadata-only extraction used by the SoundCloud/YT Music resolvers."""

    def _run() -> dict[str, Any]:  # pragma: no cover - network path
        import yt_dlp

        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "skip_download": True,
        }
        if flat:
            opts["extract_flat"] = "in_playlist"
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise DownloadFailed(f"could not extract metadata from {url}")
            result: dict[str, Any] = ydl.sanitize_info(info)
            return result

    return await asyncio.to_thread(_run)


@dataclass(slots=True)
class DownloadRequest:
    track: TrackMeta
    media_url: str
    dest: Path
    """Final destination path (already collision-resolved by the organizer)."""
    fmt: AudioFormat


class DownloadEngine:
    """Runs download requests under an ``asyncio.TaskGroup`` with a semaphore.

    ``on_progress`` is invoked from worker threads (yt-dlp progress hooks) —
    callers needing loop affinity should wrap it with
    ``loop.call_soon_threadsafe``. ``on_result`` is awaited on the event loop
    as each track finishes, so tagging/recording can stream.
    """

    def __init__(
        self,
        *,
        concurrency: int = 4,
        ydl_factory: YdlFactory | None = None,
        on_progress: ProgressCallback | None = None,
        on_result: ResultCallback | None = None,
        ffmpeg: str | None = None,
    ) -> None:
        self._concurrency = max(1, concurrency)
        self._sem = asyncio.Semaphore(self._concurrency)
        self._ydl_factory = ydl_factory or default_ydl_factory
        self._on_progress = on_progress
        self._on_result = on_result
        self._ffmpeg = ffmpeg
        self._cancel = asyncio.Event()

    def cancel(self) -> None:
        """Signal all in-flight downloads to abort at their next progress tick."""
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    async def run(self, requests: list[DownloadRequest]) -> list[DownloadResult]:
        results: list[DownloadResult | None] = [None] * len(requests)
        try:
            async with asyncio.TaskGroup() as tg:
                for i, req in enumerate(requests):
                    tg.create_task(self._guarded(i, req, results))
        except BaseException:
            # Propagating cancellation/KeyboardInterrupt: make sure worker
            # threads see the flag so they abort and clean their staging dirs.
            self._cancel.set()
            raise
        return [r for r in results if r is not None]

    async def _guarded(
        self, index: int, req: DownloadRequest, results: list[DownloadResult | None]
    ) -> None:
        async with self._sem:
            if self._cancel.is_set():
                results[index] = DownloadResult(track=req.track, status="pending")
                return
            try:
                path = await asyncio.to_thread(self._download_sync, req)
                results[index] = DownloadResult(track=req.track, status="done", file_path=path)
            except DownloadCancelled:
                results[index] = DownloadResult(track=req.track, status="pending")
            except Exception as exc:
                message = str(exc) or type(exc).__name__
                results[index] = DownloadResult(track=req.track, status="failed", error=message)
        result = results[index]
        if self._on_result is not None and result is not None:
            await self._on_result(result)

    # -- thread side -------------------------------------------------------

    def _download_sync(self, req: DownloadRequest) -> Path:
        req.dest.parent.mkdir(parents=True, exist_ok=True)
        staging = req.dest.parent / f".part-{uuid.uuid4().hex[:12]}"
        staging.mkdir(parents=True, exist_ok=True)
        try:
            opts = self._ydl_opts(req, staging)
            with self._ydl_factory(opts) as ydl:
                info = ydl.extract_info(req.media_url, download=True)
            if info is None:
                raise DownloadFailed(f"no media found at {req.media_url}")
            downloaded = self._find_output(staging, info)
            return converter.ensure_format(downloaded, req.dest, req.fmt, ffmpeg=self._ffmpeg)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _ydl_opts(self, req: DownloadRequest, staging: Path) -> dict[str, Any]:
        fmt_selector = "bestaudio/best"
        if req.fmt == "m4a":
            fmt_selector = "bestaudio[ext=m4a]/bestaudio/best"
        return {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,
            "retries": 3,
            "format": fmt_selector,
            "outtmpl": str(staging / "%(id)s.%(ext)s"),
            "progress_hooks": [self._make_hook(req)],
        }

    def _make_hook(self, req: DownloadRequest) -> Callable[[dict[str, Any]], None]:
        def hook(d: dict[str, Any]) -> None:
            if self._cancel.is_set():
                raise DownloadCancelled(req.track.external_id)
            if self._on_progress is None:
                return
            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                got = d.get("downloaded_bytes") or 0
                pct = min(100.0, (got / total) * 100.0) if total else 0.0
                speed = d.get("speed")
                speed_h = f"{speed / 1_048_576:.1f} MB/s" if speed else None
                self._on_progress(req.track.external_id, pct, speed_h)
            elif status == "finished":
                self._on_progress(req.track.external_id, 100.0, None)

        return hook

    @staticmethod
    def _find_output(staging: Path, info: dict[str, Any]) -> Path:
        for rd in info.get("requested_downloads") or []:
            fp = rd.get("filepath")
            if fp and Path(fp).exists():
                return Path(fp)
        files = sorted(
            (p for p in staging.iterdir() if p.is_file()),
            key=lambda p: p.stat().st_size,
            reverse=True,
        )
        if not files:
            raise DownloadFailed("download produced no file")
        return files[0]
