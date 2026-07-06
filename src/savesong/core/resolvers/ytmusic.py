"""YouTube Music resolver + candidate search (both via yt-dlp).

``search_candidates`` implements the spec's ``ytmusicsearch5`` operation:
a YouTube Music search returning the first N results as
:class:`MatchCandidate` for the scoring engine.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, ClassVar
from urllib.parse import quote_plus

from savesong.core import downloader
from savesong.core.resolvers.base import Resolver
from savesong.core.resolvers.detect import detect
from savesong.errors import ResolveError
from savesong.models import MatchCandidate, PlaylistMeta, Resolved, Source, TrackMeta

ExtractFn = Callable[[str], Awaitable[dict[str, Any]]]

SEARCH_LIMIT = 5


async def _default_extract(url: str) -> dict[str, Any]:
    return await downloader.extract_info_async(url, flat=True)


def _watch_url(video_id: str) -> str:
    return f"https://music.youtube.com/watch?v={video_id}"


class YTMusicResolver(Resolver):
    source: ClassVar[Source] = "ytmusic"

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
            title = str(info.get("title") or "YouTube Music Playlist")
            entries = [e for e in info.get("entries") or [] if e]
            tracks = [
                _entry_meta(entry, album=title, index=i) for i, entry in enumerate(entries, 1)
            ]
            playlist = PlaylistMeta(
                source="ytmusic",
                external_id=str(info.get("id") or detected.external_id),
                title=title,
                url=detected.url,
                tracks=tracks,
            )
            return Resolved(playlist=playlist, tracks=tracks)
        return Resolved(playlist=None, tracks=[_entry_meta(info, album=None, index=None)])


def _entry_meta(entry: dict[str, Any], *, album: str | None, index: int | None) -> TrackMeta:
    video_id = str(entry.get("id") or "")
    duration = entry.get("duration")
    artist = entry.get("artist") or entry.get("channel") or entry.get("uploader")
    thumbnails = entry.get("thumbnails") or []
    thumbnail = entry.get("thumbnail") or (thumbnails[-1].get("url") if thumbnails else None)
    return TrackMeta(
        source="ytmusic",
        external_id=video_id,
        title=str(entry.get("title") or "Unknown Title"),
        artists=[str(artist)] if artist else [],
        album=album or entry.get("album"),
        duration_ms=int(duration * 1000) if duration else None,
        cover_url=thumbnail,
        track_number=index,
        url=str(entry.get("webpage_url") or entry.get("url") or _watch_url(video_id)),
    )


async def search_candidates(
    query: str,
    *,
    limit: int = SEARCH_LIMIT,
    extract: ExtractFn | None = None,
) -> list[MatchCandidate]:
    """YouTube Music search → first ``limit`` results as match candidates.

    Falls back to plain YouTube search (``ytsearchN:``) if the music search
    extraction yields nothing.
    """
    extract_fn = extract or _default_extract
    entries: list[dict[str, Any]] = []
    try:
        info = await extract_fn(f"https://music.youtube.com/search?q={quote_plus(query)}")
        entries = [e for e in info.get("entries") or [] if e]
    except Exception:
        entries = []
    if not entries:
        try:
            info = await extract_fn(f"ytsearch{limit}:{query}")
            entries = [e for e in info.get("entries") or [] if e]
        except Exception as exc:
            raise ResolveError(f"YouTube Music search failed for {query!r}: {exc}") from exc

    candidates: list[MatchCandidate] = []
    for entry in entries[:limit]:
        video_id = entry.get("id")
        if not video_id:
            continue
        duration = entry.get("duration")
        candidates.append(
            MatchCandidate(
                video_id=str(video_id),
                title=str(entry.get("title") or ""),
                channel=str(entry.get("channel") or entry.get("uploader") or ""),
                duration_s=int(duration) if duration else None,
                view_count=entry.get("view_count"),
            )
        )
    return candidates
