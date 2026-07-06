"""Optional ffmpeg conversion/remux into the requested audio format."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from savesong.errors import ConversionError
from savesong.models import AudioFormat

_OPUS_SOURCES = {".webm", ".opus", ".ogg", ".oga"}

RunProcess = Callable[..., "subprocess.CompletedProcess[bytes]"]


def target_matches(src: Path, fmt: AudioFormat) -> bool:
    """True when the downloaded file already has the requested container."""
    return src.suffix.lower().lstrip(".") == fmt


def ffmpeg_args(src: Path, dest: Path, fmt: AudioFormat) -> list[str]:
    """Build the ffmpeg argument list (pure, unit-testable).

    Opus streams inside webm/ogg are remuxed with ``-c:a copy``; anything else
    is transcoded.
    """
    args = ["-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-vn"]
    if fmt == "opus":
        if src.suffix.lower() in _OPUS_SOURCES:
            args += ["-c:a", "copy"]
        else:
            args += ["-c:a", "libopus", "-b:a", "160k"]
    elif fmt == "m4a":
        args += ["-c:a", "aac", "-b:a", "192k"]
    else:  # mp3
        args += ["-c:a", "libmp3lame", "-q:a", "0"]
    return [*args, str(dest)]


def ensure_format(
    src: Path,
    dest: Path,
    fmt: AudioFormat,
    *,
    ffmpeg: str | None = None,
    run: RunProcess = subprocess.run,
) -> Path:
    """Move ``src`` to ``dest``, converting with ffmpeg when the container differs.

    The rename is atomic (same filesystem: staging lives next to ``dest``).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if target_matches(src, fmt):
        os.replace(src, dest)
        return dest

    exe = ffmpeg or shutil.which("ffmpeg")
    if exe is None:
        raise ConversionError(
            f"ffmpeg is required to produce .{fmt} from {src.suffix or 'unknown'} "
            "— install ffmpeg or pick a --format matching the native download"
        )
    tmp = src.with_name(f"{src.stem}.convert.{fmt}")
    cmd = [exe, *ffmpeg_args(src, tmp, fmt)]
    proc: Any = run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace")[-400:] if proc.stderr else ""
        raise ConversionError(f"ffmpeg exited with {proc.returncode}: {stderr}")
    if not tmp.exists():
        raise ConversionError("ffmpeg reported success but produced no output file")
    os.replace(tmp, dest)
    return dest
