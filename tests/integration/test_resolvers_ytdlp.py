"""SoundCloud / YT Music resolvers and candidate search over a stubbed extractor."""

from __future__ import annotations

from typing import Any

import pytest

from savesong.core.resolvers.soundcloud import SoundCloudResolver
from savesong.core.resolvers.ytmusic import YTMusicResolver, search_candidates
from savesong.errors import ResolveError

SC_SET = {
    "_type": "playlist",
    "id": 777001,
    "title": "Late Night Mix",
    "entries": [
        {
            "id": 111,
            "title": "First Wave",
            "uploader": "dj-orbit",
            "duration": 201.5,
            "webpage_url": "https://soundcloud.com/dj-orbit/first-wave",
            "thumbnails": [
                {"url": "https://i1.sndcdn.com/small.jpg"},
                {"url": "https://i1.sndcdn.com/big.jpg"},
            ],
        },
        {
            "id": 222,
            "title": "Second Wave",
            "uploader": "dj-orbit",
            "duration": 245.0,
            "url": "https://soundcloud.com/dj-orbit/second-wave",
        },
    ],
}

SC_TRACK = {
    "id": 333,
    "title": "Solo Drop",
    "uploader": "bass-cadet",
    "duration": 180.0,
    "webpage_url": "https://soundcloud.com/bass-cadet/solo-drop",
    "thumbnail": "https://i1.sndcdn.com/solo.jpg",
}

YTM_PLAYLIST = {
    "_type": "playlist",
    "id": "OLAK5uy_test",
    "title": "Album Playlist",
    "entries": [
        {
            "id": "vid00000001",
            "title": "Opening Theme",
            "channel": "Portal Frames - Topic",
            "duration": 214,
            "url": "https://music.youtube.com/watch?v=vid00000001",
        },
        {
            "id": "vid00000002",
            "title": "Closing Theme",
            "uploader": "Portal Frames - Topic",
            "duration": 189,
        },
    ],
}


def make_extract(response: dict[str, Any]) -> Any:
    async def extract(url: str) -> dict[str, Any]:
        return response

    return extract


async def test_soundcloud_set(settings: Any) -> None:
    resolver = SoundCloudResolver(extract=make_extract(SC_SET))
    resolved = await resolver.resolve("https://soundcloud.com/dj-orbit/sets/late-night-mix")
    assert resolved.playlist is not None
    assert resolved.playlist.source == "soundcloud"
    assert resolved.playlist.title == "Late Night Mix"
    assert len(resolved.tracks) == 2
    t1, t2 = resolved.tracks
    assert t1.external_id == "111"
    assert t1.artists == ["dj-orbit"]
    assert t1.album == "Late Night Mix"
    assert t1.duration_ms == 201500
    assert t1.track_number == 1
    assert t1.url == "https://soundcloud.com/dj-orbit/first-wave"
    assert t1.cover_url == "https://i1.sndcdn.com/big.jpg"
    assert t2.url == "https://soundcloud.com/dj-orbit/second-wave"
    assert t2.track_number == 2


async def test_soundcloud_single_track() -> None:
    resolver = SoundCloudResolver(extract=make_extract(SC_TRACK))
    resolved = await resolver.resolve("https://soundcloud.com/bass-cadet/solo-drop")
    assert resolved.playlist is None
    (track,) = resolved.tracks
    assert track.title == "Solo Drop"
    assert track.duration_ms == 180000
    assert track.cover_url == "https://i1.sndcdn.com/solo.jpg"


async def test_soundcloud_extractor_error_wrapped() -> None:
    async def broken(url: str) -> dict[str, Any]:
        raise RuntimeError("network down")

    resolver = SoundCloudResolver(extract=broken)
    with pytest.raises(ResolveError, match="yt-dlp failed"):
        await resolver.resolve("https://soundcloud.com/a/b")


async def test_ytmusic_playlist() -> None:
    resolver = YTMusicResolver(extract=make_extract(YTM_PLAYLIST))
    resolved = await resolver.resolve("https://music.youtube.com/playlist?list=OLAK5uy_test")
    assert resolved.playlist is not None
    assert resolved.playlist.source == "ytmusic"
    assert len(resolved.tracks) == 2
    t1, t2 = resolved.tracks
    assert t1.external_id == "vid00000001"
    assert t1.artists == ["Portal Frames - Topic"]
    assert t2.url == "https://music.youtube.com/watch?v=vid00000002"


async def test_ytmusic_single_video() -> None:
    single = {
        "id": "vid00000009",
        "title": "One Off",
        "channel": "Someone",
        "duration": 100,
        "webpage_url": "https://music.youtube.com/watch?v=vid00000009",
    }
    resolver = YTMusicResolver(extract=make_extract(single))
    resolved = await resolver.resolve("https://music.youtube.com/watch?v=vid00000009")
    assert resolved.playlist is None
    assert resolved.tracks[0].external_id == "vid00000009"


async def test_search_candidates_maps_and_limits(ytm_search_fx: dict[str, Any]) -> None:
    calls: list[str] = []

    async def extract(url: str) -> dict[str, Any]:
        calls.append(url)
        return ytm_search_fx["response"]

    results = await search_candidates("Portal Frames Neon Coastline", extract=extract)
    assert len(results) == 5  # sixth entry trimmed by the limit
    first = results[0]
    assert first.video_id == "yt_correct01"
    assert first.channel == "Portal Frames - Topic"
    assert first.duration_s == 214
    assert first.view_count == 1200000
    assert "music.youtube.com/search?q=Portal+Frames+Neon+Coastline" in calls[0]


async def test_search_candidates_falls_back_to_ytsearch(ytm_search_fx: dict[str, Any]) -> None:
    calls: list[str] = []

    async def extract(url: str) -> dict[str, Any]:
        calls.append(url)
        if url.startswith("https://music.youtube.com"):
            raise RuntimeError("music search broken")
        return ytm_search_fx["response"]

    results = await search_candidates("some song", extract=extract)
    assert len(results) == 5
    assert calls[1].startswith("ytsearch5:")


async def test_search_candidates_total_failure_raises() -> None:
    async def extract(url: str) -> dict[str, Any]:
        raise RuntimeError("nope")

    with pytest.raises(ResolveError, match="search failed"):
        await search_candidates("q", extract=extract)
