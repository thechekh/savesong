"""Write metadata + embedded cover art with mutagen (opus / m4a / mp3)."""

from __future__ import annotations

import base64
from pathlib import Path

from savesong.errors import TaggingError
from savesong.models import TrackMeta


def tag_file(
    path: Path,
    track: TrackMeta,
    cover: bytes | None = None,
    cover_mime: str = "image/jpeg",
) -> None:
    """Tag ``path`` in place. Container is derived from the file extension."""
    suffix = path.suffix.lower()
    if suffix == ".opus":
        _tag_opus(path, track, cover, cover_mime)
    elif suffix == ".mp3":
        _tag_mp3(path, track, cover, cover_mime)
    elif suffix in {".m4a", ".mp4"}:
        _tag_mp4(path, track, cover, cover_mime)
    else:
        raise TaggingError(f"unsupported audio container: {suffix or path.name}")


def _tag_opus(path: Path, track: TrackMeta, cover: bytes | None, mime: str) -> None:
    from mutagen.flac import Picture
    from mutagen.oggopus import OggOpus

    audio = OggOpus(str(path))
    audio["title"] = [track.title]
    audio["artist"] = track.artists or ["Unknown Artist"]
    if track.album:
        audio["album"] = [track.album]
    if track.track_number:
        audio["tracknumber"] = [str(track.track_number)]
    if track.release_year:
        audio["date"] = [str(track.release_year)]
    if cover is not None:
        picture = Picture()
        picture.type = 3  # front cover
        picture.mime = mime
        picture.data = cover
        audio["metadata_block_picture"] = [base64.b64encode(picture.write()).decode("ascii")]
    audio.save()


def _tag_mp3(path: Path, track: TrackMeta, cover: bytes | None, mime: str) -> None:
    from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TRCK, ID3NoHeaderError

    try:
        tags = ID3(str(path))
    except ID3NoHeaderError:
        tags = ID3()
    tags.setall("TIT2", [TIT2(encoding=3, text=[track.title])])
    tags.setall("TPE1", [TPE1(encoding=3, text=track.artists or ["Unknown Artist"])])
    if track.album:
        tags.setall("TALB", [TALB(encoding=3, text=[track.album])])
    if track.track_number:
        tags.setall("TRCK", [TRCK(encoding=3, text=[str(track.track_number)])])
    if track.release_year:
        tags.setall("TDRC", [TDRC(encoding=3, text=[str(track.release_year)])])
    if cover is not None:
        tags.setall("APIC", [APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover)])
    tags.save(str(path))


def _tag_mp4(path: Path, track: TrackMeta, cover: bytes | None, mime: str) -> None:
    from mutagen.mp4 import MP4, MP4Cover

    audio = MP4(str(path))
    audio["\xa9nam"] = [track.title]
    audio["\xa9ART"] = [track.artist_display]
    if track.album:
        audio["\xa9alb"] = [track.album]
    if track.track_number:
        audio["trkn"] = [(track.track_number, 0)]
    if track.release_year:
        audio["\xa9day"] = [str(track.release_year)]
    if cover is not None:
        image_format = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
        audio["covr"] = [MP4Cover(cover, imageformat=image_format)]
    audio.save()
