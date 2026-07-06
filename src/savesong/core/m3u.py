"""Write ``.m3u8`` (UTF-8 extended M3U) playlists."""

from __future__ import annotations

import os
from pathlib import Path

from savesong.models import TrackMeta


def write_m3u8(
    dest: Path,
    entries: list[tuple[Path, TrackMeta]],
    *,
    relative: bool = False,
) -> Path:
    """Write an ``#EXTM3U`` playlist for ``entries`` (file path + metadata).

    With ``relative=True`` file paths are written relative to the playlist
    location using forward slashes (portable across players and platforms).
    """
    lines = ["#EXTM3U"]
    for file_path, track in entries:
        seconds = round(track.duration_ms / 1000) if track.duration_ms else -1
        lines.append(f"#EXTINF:{seconds},{track.artist_display} - {track.title}")
        if relative:
            lines.append(Path(os.path.relpath(file_path, dest.parent)).as_posix())
        else:
            lines.append(str(file_path))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest
