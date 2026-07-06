"""Tagger round-trips on real (generated, CC0) audio files."""

from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path

import pytest

from savesong.core.tagger import tag_file
from savesong.errors import TaggingError
from savesong.models import TrackMeta

META = TrackMeta(
    source="spotify",
    external_id="t1",
    title="Neon Coastline",
    artists=["Portal Frames", "Vela Ray"],
    album="Night Drive OST",
    duration_ms=214000,
    track_number=3,
    release_year=2019,
)


def test_opus_round_trip(tmp_path: Path, sample_opus: Path, cover_png: bytes) -> None:
    from mutagen.flac import Picture
    from mutagen.oggopus import OggOpus

    target = tmp_path / "song.opus"
    shutil.copyfile(sample_opus, target)
    tag_file(target, META, cover=cover_png, cover_mime="image/png")

    audio = OggOpus(str(target))
    assert audio["title"] == ["Neon Coastline"]
    assert audio["artist"] == ["Portal Frames", "Vela Ray"]
    assert audio["album"] == ["Night Drive OST"]
    assert audio["tracknumber"] == ["3"]
    assert audio["date"] == ["2019"]
    picture = Picture(base64.b64decode(audio["metadata_block_picture"][0]))
    assert picture.mime == "image/png"
    assert picture.data == cover_png


def test_opus_retag_overwrites(tmp_path: Path, sample_opus: Path) -> None:
    from mutagen.oggopus import OggOpus

    target = tmp_path / "song.opus"
    shutil.copyfile(sample_opus, target)
    tag_file(target, META)
    updated = META.model_copy(update={"title": "Renamed"})
    tag_file(target, updated)
    assert OggOpus(str(target))["title"] == ["Renamed"]


def test_mp3_round_trip(tmp_path: Path, sample_mp3: Path, cover_png: bytes) -> None:
    from mutagen.id3 import ID3

    target = tmp_path / "song.mp3"
    shutil.copyfile(sample_mp3, target)
    tag_file(target, META, cover=cover_png, cover_mime="image/png")

    tags = ID3(str(target))
    assert tags["TIT2"].text == ["Neon Coastline"]
    assert list(tags["TPE1"].text) == ["Portal Frames", "Vela Ray"]
    assert tags["TALB"].text == ["Night Drive OST"]
    assert tags["TRCK"].text == ["3"]
    assert str(tags["TDRC"].text[0]) == "2019"
    apics = tags.getall("APIC")
    assert apics and apics[0].data == cover_png and apics[0].mime == "image/png"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg to generate an m4a")
def test_m4a_round_trip(tmp_path: Path, cover_png: bytes) -> None:
    from mutagen.mp4 import MP4

    target = tmp_path / "song.m4a"
    subprocess.run(
        [
            "ffmpeg",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=mono",
            "-t",
            "1",
            "-c:a",
            "aac",
            "-loglevel",
            "error",
            str(target),
        ],
        check=True,
    )
    tag_file(target, META, cover=cover_png, cover_mime="image/png")

    audio = MP4(str(target))
    assert audio["\xa9nam"] == ["Neon Coastline"]
    assert audio["\xa9ART"] == ["Portal Frames, Vela Ray"]
    assert audio["\xa9alb"] == ["Night Drive OST"]
    assert audio["trkn"] == [(3, 0)]
    assert audio["\xa9day"] == ["2019"]
    assert bytes(audio["covr"][0]) == cover_png


def test_unsupported_container(tmp_path: Path) -> None:
    weird = tmp_path / "song.wav"
    weird.write_bytes(b"RIFF")
    with pytest.raises(TaggingError):
        tag_file(weird, META)
