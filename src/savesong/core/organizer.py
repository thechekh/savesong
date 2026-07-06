"""Filesystem layout: ``{artist}/{album or playlist}/{nn} - {title}.{ext}``.

Pure path construction — cross-platform sanitization, length clamping, and
collision handling via an injectable ``exists`` predicate.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from pathlib import Path

MAX_COMPONENT_LEN = 120

_FORBIDDEN_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WS_RE = re.compile(r"\s+")


def sanitize_component(name: str, max_len: int = MAX_COMPONENT_LEN) -> str:
    """Make a single path component safe on Windows, macOS, and Linux."""
    s = unicodedata.normalize("NFC", name)
    s = _FORBIDDEN_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    s = s.rstrip(" .")
    if len(s) > max_len:
        s = s[:max_len].rstrip(" .")
    return s or "_"


def track_stem(index: int | None, title: str) -> str:
    """``{nn} - {title}`` (or just the title for standalone tracks)."""
    return f"{index:02d} - {title}" if index is not None else title


def build_track_path(
    music_dir: Path,
    artist: str,
    collection: str,
    index: int | None,
    title: str,
    ext: str,
    *,
    exists: Callable[[Path], bool] | None = None,
) -> Path:
    """Resolve the final file path; collisions get a `` (2)`` suffix before the extension."""
    exists_fn = exists if exists is not None else (lambda p: p.exists())
    directory = (
        music_dir
        / sanitize_component(artist or "Unknown Artist")
        / sanitize_component(collection or "Unknown Album")
    )
    stem = sanitize_component(track_stem(index, title))
    candidate = directory / f"{stem}.{ext}"
    n = 2
    while exists_fn(candidate):
        candidate = directory / f"{stem} ({n}).{ext}"
        n += 1
    return candidate
