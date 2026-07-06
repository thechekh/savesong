"""URL source detection: spotify | soundcloud | ytmusic, playlist | track."""

from __future__ import annotations

import re
from typing import Literal, NamedTuple

from savesong.errors import UnsupportedURLError
from savesong.models import Source

Kind = Literal["playlist", "track"]

_SPOTIFY_RE = re.compile(
    r"open\.spotify\.com/(?:intl-[a-z-]+/)?(playlist|track|album)/([A-Za-z0-9]{10,40})",
    re.IGNORECASE,
)
_YT_PLAYLIST_RE = re.compile(
    r"(?:music\.)?youtube\.com/playlist\?(?:[^#\s]*&)?list=([A-Za-z0-9_-]+)", re.IGNORECASE
)
_YT_WATCH_RE = re.compile(
    r"(?:music\.)?youtube\.com/watch\?(?:[^#\s]*&)?v=([A-Za-z0-9_-]{11})", re.IGNORECASE
)
_YOUTU_BE_RE = re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})", re.IGNORECASE)
_SC_SET_RE = re.compile(r"soundcloud\.com/([^/?#\s]+)/sets/([^/?#\s]+)", re.IGNORECASE)
_SC_TRACK_RE = re.compile(r"soundcloud\.com/([^/?#\s]+)/([^/?#\s]+)", re.IGNORECASE)

_SC_RESERVED = {
    "discover",
    "stream",
    "upload",
    "you",
    "search",
    "charts",
    "people",
    "pages",
    "popular",
    "tags",
    "terms-of-use",
}


class DetectedURL(NamedTuple):
    source: Source
    kind: Kind
    external_id: str
    url: str
    """Normalized canonical URL."""


def detect(url: str) -> DetectedURL:
    """Classify a URL; raises :class:`UnsupportedURLError` for anything else."""
    u = url.strip()

    if m := _SPOTIFY_RE.search(u):
        kind, sid = m.group(1).lower(), m.group(2)
        if kind == "album":
            raise UnsupportedURLError(
                "Spotify album URLs are not supported — use a playlist or track URL"
            )
        return DetectedURL(
            "spotify",
            "playlist" if kind == "playlist" else "track",
            sid,
            f"https://open.spotify.com/{kind}/{sid}",
        )

    if m := _YT_PLAYLIST_RE.search(u):
        pid = m.group(1)
        return DetectedURL(
            "ytmusic", "playlist", pid, f"https://music.youtube.com/playlist?list={pid}"
        )

    if m := _YT_WATCH_RE.search(u):
        vid = m.group(1)
        return DetectedURL("ytmusic", "track", vid, f"https://music.youtube.com/watch?v={vid}")

    if m := _YOUTU_BE_RE.search(u):
        vid = m.group(1)
        return DetectedURL("ytmusic", "track", vid, f"https://music.youtube.com/watch?v={vid}")

    if m := _SC_SET_RE.search(u):
        user, slug = m.group(1).lower(), m.group(2).lower()
        return DetectedURL(
            "soundcloud",
            "playlist",
            f"{user}/sets/{slug}",
            f"https://soundcloud.com/{user}/sets/{slug}",
        )

    if m := _SC_TRACK_RE.search(u):
        user, slug = m.group(1).lower(), m.group(2).lower()
        if user not in _SC_RESERVED and slug not in _SC_RESERVED:
            return DetectedURL(
                "soundcloud",
                "track",
                f"{user}/{slug}",
                f"https://soundcloud.com/{user}/{slug}",
            )

    raise UnsupportedURLError(f"Unsupported URL: {url}")
