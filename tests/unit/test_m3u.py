"""m3u8 writer."""

from __future__ import annotations

from pathlib import Path

from savesong.core.m3u import write_m3u8
from savesong.models import TrackMeta


def meta(title: str, artist: str, duration_ms: int | None) -> TrackMeta:
    return TrackMeta(
        source="ytmusic",
        external_id=title,
        title=title,
        artists=[artist],
        duration_ms=duration_ms,
    )


def test_write_absolute(tmp_path: Path) -> None:
    f1 = tmp_path / "Artist" / "Album" / "01 - Song.opus"
    dest = tmp_path / "Playlist.m3u8"
    out = write_m3u8(dest, [(f1, meta("Sóng ✨", "Ärtist", 214000))])
    text = out.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "#EXTM3U"
    assert lines[1] == "#EXTINF:214,Ärtist - Sóng ✨"
    assert lines[2] == str(f1)


def test_write_relative_uses_forward_slashes(tmp_path: Path) -> None:
    f1 = tmp_path / "Artist" / "Album" / "01 - Song.opus"
    dest = tmp_path / "Playlist.m3u8"
    out = write_m3u8(dest, [(f1, meta("Song", "Artist", 90000))], relative=True)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[2] == "Artist/Album/01 - Song.opus"


def test_missing_duration_writes_minus_one(tmp_path: Path) -> None:
    dest = tmp_path / "p.m3u8"
    write_m3u8(dest, [(tmp_path / "x.opus", meta("Song", "Artist", None))])
    assert "#EXTINF:-1,Artist - Song" in dest.read_text(encoding="utf-8")


def test_creates_parent_dirs(tmp_path: Path) -> None:
    dest = tmp_path / "nested" / "deep" / "p.m3u8"
    write_m3u8(dest, [])
    assert dest.read_text(encoding="utf-8") == "#EXTM3U\n"
