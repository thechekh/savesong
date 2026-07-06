"""SoundCloud resolver via yt-dlp flat playlist extraction."""

from __future__ import annotations

from typing import Any, ClassVar

from savesong.core import downloader
from savesong.core.resolvers.base import Resolver
from savesong.core.resolvers.detect import detect
from savesong.core.resolvers.ytmusic import ExtractFn
from savesong.errors import ResolveError
from savesong.models import PlaylistMeta, Resolved, Source, TrackMeta


async def _default_extract(url: str) -> dict[str, Any]:
    return await downloader.extract_info_async(url, flat=True)


class SoundCloudResolver(Resolver):
    source: ClassVar[Source] = "soundcloud"

    def __init__(self, *, extract: ExtractFn | None = None) -> None:
        self._extract = extract or _default_extract

    async def resolve(self, url: str) -> Resolved:
        detected = detect(url)
        try:
            info = await self._extract(detected.url)
        except ResolveError:
            raise
        except Exception as exc:
            raise ResolveError(f"yt-dlp failed on {detected.url}: {exc}") from exc

        if info.get("_type") == "playlist" or "entries" in info:
            title = str(info.get("title") or "SoundCloud Set")
            entries = [e for e in info.get("entries") or [] if e]
            tracks = [
                _entry_meta(entry, album=title, index=i) for i, entry in enumerate(entries, 1)
            ]
            playlist = PlaylistMeta(
                source="soundcloud",
                external_id=str(info.get("id") or detected.external_id),
                title=title,
                url=detected.url,
                tracks=tracks,
            )
            return Resolved(playlist=playlist, tracks=tracks)
        return Resolved(playlist=None, tracks=[_entry_meta(info, album=None, index=None)])


def _entry_meta(entry: dict[str, Any], *, album: str | None, index: int | None) -> TrackMeta:
    duration = entry.get("duration")
    uploader = entry.get("uploader") or entry.get("artist") or entry.get("uploader_id")
    thumbnails = entry.get("thumbnails") or []
    thumbnail = entry.get("thumbnail") or (thumbnails[-1].get("url") if thumbnails else None)
    return TrackMeta(
        source="soundcloud",
        external_id=str(entry.get("id") or entry.get("url") or "unknown"),
        title=str(entry.get("title") or "Unknown Title"),
        artists=[str(uploader)] if uploader else [],
        album=album,
        duration_ms=int(duration * 1000) if duration else None,
        cover_url=thumbnail,
        track_number=index,
        url=str(entry.get("webpage_url") or entry.get("url") or ""),
    )
