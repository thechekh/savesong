"""Organizer path templating: sanitization, unicode, collisions."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from savesong.core import organizer


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AC/DC", "AC DC"),
        ('He said: "hi" <ok>?*|', "He said hi ok"),
        ("Trailing dots...", "Trailing dots"),
        ("Trailing space ", "Trailing space"),
        ("  collapse   spaces  ", "collapse spaces"),
        ("", "_"),
        ("...", "_"),
        ("normal name", "normal name"),
    ],
)
def test_sanitize_component(raw: str, expected: str) -> None:
    assert organizer.sanitize_component(raw) == expected


def test_sanitize_strips_control_chars() -> None:
    assert organizer.sanitize_component("a\x00b\x1fc") == "a b c"


def test_sanitize_unicode_nfc() -> None:
    decomposed = unicodedata.normalize("NFD", "Beyoncé")
    result = organizer.sanitize_component(decomposed)
    assert result == "Beyoncé"
    assert unicodedata.is_normalized("NFC", result)


def test_sanitize_clamps_length() -> None:
    long = "x" * 500
    assert len(organizer.sanitize_component(long)) == organizer.MAX_COMPONENT_LEN


def test_track_stem() -> None:
    assert organizer.track_stem(3, "Song") == "03 - Song"
    assert organizer.track_stem(None, "Song") == "Song"


def test_build_track_path_layout(tmp_path: Path) -> None:
    p = organizer.build_track_path(tmp_path, "Artist", "Album", 1, "Song", "opus")
    assert p == tmp_path / "Artist" / "Album" / "01 - Song.opus"


def test_build_track_path_sanitizes_all_components(tmp_path: Path) -> None:
    p = organizer.build_track_path(tmp_path, "AC/DC", "Back: In Black", 2, 'T?N*T"', "mp3")
    assert p == tmp_path / "AC DC" / "Back In Black" / "02 - T N T.mp3"


def test_build_track_path_collision_suffix(tmp_path: Path) -> None:
    taken = {
        tmp_path / "A" / "B" / "01 - Song.opus",
        tmp_path / "A" / "B" / "01 - Song (2).opus",
    }
    p = organizer.build_track_path(
        tmp_path, "A", "B", 1, "Song", "opus", exists=lambda x: x in taken
    )
    assert p.name == "01 - Song (3).opus"


def test_build_track_path_defaults_for_missing_names(tmp_path: Path) -> None:
    p = organizer.build_track_path(tmp_path, "", "", None, "Song", "opus")
    assert p == tmp_path / "Unknown Artist" / "Unknown Album" / "Song.opus"
