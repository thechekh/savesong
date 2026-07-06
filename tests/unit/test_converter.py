"""Converter: ffmpeg argument building and ensure_format flows (ffmpeg stubbed)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from savesong.core import converter
from savesong.errors import ConversionError


def test_target_matches() -> None:
    assert converter.target_matches(Path("x.opus"), "opus")
    assert converter.target_matches(Path("x.OPUS"), "opus")
    assert not converter.target_matches(Path("x.webm"), "opus")


def test_ffmpeg_args_opus_remux_from_webm(tmp_path: Path) -> None:
    args = converter.ffmpeg_args(tmp_path / "in.webm", tmp_path / "out.opus", "opus")
    assert ["-c:a", "copy"] == args[args.index("-c:a") : args.index("-c:a") + 2]
    assert args[-1].endswith("out.opus")
    assert "-vn" in args


def test_ffmpeg_args_opus_transcode_from_mp3(tmp_path: Path) -> None:
    args = converter.ffmpeg_args(tmp_path / "in.mp3", tmp_path / "out.opus", "opus")
    assert "libopus" in args


def test_ffmpeg_args_mp3_and_m4a(tmp_path: Path) -> None:
    assert "libmp3lame" in converter.ffmpeg_args(tmp_path / "a.webm", tmp_path / "b.mp3", "mp3")
    assert "aac" in converter.ffmpeg_args(tmp_path / "a.webm", tmp_path / "b.m4a", "m4a")


def test_ensure_format_same_ext_is_atomic_rename(tmp_path: Path) -> None:
    src = tmp_path / "stage" / "x.opus"
    src.parent.mkdir()
    src.write_bytes(b"audio")
    dest = tmp_path / "final" / "song.opus"
    result = converter.ensure_format(src, dest, "opus")
    assert result == dest
    assert dest.read_bytes() == b"audio"
    assert not src.exists()


def test_ensure_format_requires_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda _: None)
    src = tmp_path / "x.webm"
    src.write_bytes(b"vid")
    with pytest.raises(ConversionError, match="ffmpeg is required"):
        converter.ensure_format(src, tmp_path / "out.opus", "opus")


def test_ensure_format_converts_via_runner(tmp_path: Path) -> None:
    src = tmp_path / "x.webm"
    src.write_bytes(b"vid")
    dest = tmp_path / "out" / "song.opus"
    commands: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"converted")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    result = converter.ensure_format(src, dest, "opus", ffmpeg="ffmpeg-stub", run=fake_run)
    assert result == dest
    assert dest.read_bytes() == b"converted"
    assert commands and commands[0][0] == "ffmpeg-stub"


def test_ensure_format_raises_on_nonzero_exit(tmp_path: Path) -> None:
    src = tmp_path / "x.webm"
    src.write_bytes(b"vid")

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 1, b"", b"boom: unsupported codec")

    with pytest.raises(ConversionError, match="unsupported codec"):
        converter.ensure_format(src, tmp_path / "o.opus", "opus", ffmpeg="f", run=fake_run)


def test_ensure_format_raises_when_no_output(tmp_path: Path) -> None:
    src = tmp_path / "x.webm"
    src.write_bytes(b"vid")

    def fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    with pytest.raises(ConversionError, match="no output"):
        converter.ensure_format(src, tmp_path / "o.opus", "opus", ffmpeg="f", run=fake_run)
