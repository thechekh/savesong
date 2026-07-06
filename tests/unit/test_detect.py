"""URL source detection."""

from __future__ import annotations

import pytest

from savesong.core.resolvers import detect
from savesong.errors import UnsupportedURLError


@pytest.mark.parametrize(
    ("url", "source", "kind", "external_id"),
    [
        (
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
            "spotify",
            "playlist",
            "37i9dQZF1DXcBWIGoYBM5M",
        ),
        (
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc123",
            "spotify",
            "playlist",
            "37i9dQZF1DXcBWIGoYBM5M",
        ),
        (
            "https://open.spotify.com/intl-de/track/0VjIjW4GlUZAMYd2vXMi3b",
            "spotify",
            "track",
            "0VjIjW4GlUZAMYd2vXMi3b",
        ),
        (
            "https://music.youtube.com/playlist?list=OLAK5uy_kfp3xyz",
            "ytmusic",
            "playlist",
            "OLAK5uy_kfp3xyz",
        ),
        (
            "https://www.youtube.com/playlist?list=PL1234567890",
            "ytmusic",
            "playlist",
            "PL1234567890",
        ),
        (
            "https://music.youtube.com/watch?v=dQw4w9WgXcQ&si=xyz",
            "ytmusic",
            "track",
            "dQw4w9WgXcQ",
        ),
        ("https://youtu.be/dQw4w9WgXcQ", "ytmusic", "track", "dQw4w9WgXcQ"),
        (
            "https://www.youtube.com/watch?feature=shared&v=dQw4w9WgXcQ",
            "ytmusic",
            "track",
            "dQw4w9WgXcQ",
        ),
        (
            "https://soundcloud.com/artist-name/sets/my-mix",
            "soundcloud",
            "playlist",
            "artist-name/sets/my-mix",
        ),
        (
            "https://soundcloud.com/artist-name/one-track?in=whatever",
            "soundcloud",
            "track",
            "artist-name/one-track",
        ),
    ],
)
def test_detect_supported(url: str, source: str, kind: str, external_id: str) -> None:
    result = detect(url)
    assert result.source == source
    assert result.kind == kind
    assert result.external_id == external_id


def test_detect_normalizes_urls() -> None:
    result = detect("http://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert result.url == "https://music.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        "https://open.spotify.com/album/4aawyAB9vmqN3uQ7FjRGTy",
        "https://example.com/some/page",
        "https://soundcloud.com/discover",
        "not a url at all",
        "",
    ],
)
def test_detect_unsupported(url: str) -> None:
    with pytest.raises(UnsupportedURLError):
        detect(url)
