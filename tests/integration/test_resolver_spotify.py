"""Spotify resolver against a respx-mocked Web API (recorded fixture shapes)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from savesong.core.resolvers.spotify import SpotifyResolver
from savesong.errors import ResolveError, SpotifyAuthError

PLAYLIST_URL = "https://open.spotify.com/playlist/5FpYt2XoNbXvJp0k4v3Kx1"
TRACK_URL = "https://open.spotify.com/track/0VjIjW4GlUZAMYd2vXMi3b"


def install_routes(fx: dict[str, Any]) -> None:
    respx.post("https://accounts.spotify.com/api/token").respond(
        json={"access_token": "test-token", "expires_in": 3600}
    )
    respx.get(
        url__regex=r"https://api\.spotify\.com/v1/playlists/5FpYt2XoNbXvJp0k4v3Kx1(\?.*)?$"
    ).respond(json=fx["playlist"])

    def tracks_page(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", "0"))
        page = fx["tracks_page_1"] if offset == 0 else fx["tracks_page_2"]
        return httpx.Response(200, json=page)

    respx.get(
        url__regex=r"https://api\.spotify\.com/v1/playlists/5FpYt2XoNbXvJp0k4v3Kx1/tracks.*"
    ).mock(side_effect=tracks_page)
    respx.get("https://api.spotify.com/v1/tracks/0VjIjW4GlUZAMYd2vXMi3b").respond(
        json=fx["track_single"]
    )


@respx.mock
async def test_playlist_resolution_pages_and_skips(spotify_fx: dict[str, Any]) -> None:
    install_routes(spotify_fx)
    resolver = SpotifyResolver("id", "secret")
    resolved = await resolver.resolve(PLAYLIST_URL)
    await resolver.aclose()

    assert resolved.playlist is not None
    assert resolved.playlist.title == "Synthwave Essentials"
    # 4 items on page 1 (one null, one local) + 1 on page 2 → 3 tracks
    assert [t.title for t in resolved.tracks] == [
        "Neon Coastline",
        "Chrome Sunset (feat. Vela Ray)",
        "Analog Hearts",
    ]
    first = resolved.tracks[0]
    assert first.source == "spotify"
    assert first.external_id == "3n3Ppam7vgaVa1iaRUc9Lp"
    assert first.artists == ["Portal Frames"]
    assert first.album == "Night Drive OST"
    assert first.duration_ms == 214000
    assert first.isrc == "USXXX2600001"
    assert first.cover_url == "https://i.scdn.co/image/cover-large-001"
    assert first.track_number == 1
    assert first.release_year == 2019
    second = resolved.tracks[1]
    assert second.artists == ["Portal Frames", "Vela Ray"]


@respx.mock
async def test_single_track_resolution(spotify_fx: dict[str, Any]) -> None:
    install_routes(spotify_fx)
    resolver = SpotifyResolver("id", "secret")
    resolved = await resolver.resolve(TRACK_URL)
    await resolver.aclose()
    assert resolved.playlist is None
    assert len(resolved.tracks) == 1
    assert resolved.tracks[0].title == "Neon Coastline"


async def test_missing_credentials_raise() -> None:
    resolver = SpotifyResolver(None, None)
    with pytest.raises(SpotifyAuthError, match="credentials required"):
        await resolver.resolve(PLAYLIST_URL)


@respx.mock
async def test_rejected_credentials_raise() -> None:
    respx.post("https://accounts.spotify.com/api/token").respond(
        status_code=401, json={"error": "invalid_client"}
    )
    resolver = SpotifyResolver("bad", "creds")
    with pytest.raises(SpotifyAuthError, match="rejected"):
        await resolver.resolve(PLAYLIST_URL)
    await resolver.aclose()


@respx.mock
async def test_token_refresh_on_401(spotify_fx: dict[str, Any]) -> None:
    respx.post("https://accounts.spotify.com/api/token").respond(
        json={"access_token": "tok", "expires_in": 3600}
    )
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(401)
        return httpx.Response(200, json=spotify_fx["track_single"])

    respx.get("https://api.spotify.com/v1/tracks/0VjIjW4GlUZAMYd2vXMi3b").mock(side_effect=flaky)
    resolver = SpotifyResolver("id", "secret")
    resolved = await resolver.resolve(TRACK_URL)
    await resolver.aclose()
    assert resolved.tracks[0].title == "Neon Coastline"
    assert calls["n"] == 2


@respx.mock
async def test_premium_block_403_gives_actionable_error() -> None:
    respx.post("https://accounts.spotify.com/api/token").respond(
        json={"access_token": "tok", "expires_in": 3600}
    )
    respx.get("https://api.spotify.com/v1/tracks/0VjIjW4GlUZAMYd2vXMi3b").respond(
        status_code=403,
        text="Active premium subscription required for the owner of the app.",
    )
    resolver = SpotifyResolver("id", "secret")
    with pytest.raises(SpotifyAuthError, match="[Pp]remium"):
        await resolver.resolve(TRACK_URL)
    await resolver.aclose()


@respx.mock
async def test_not_found_raises_resolve_error() -> None:
    respx.post("https://accounts.spotify.com/api/token").respond(
        json={"access_token": "tok", "expires_in": 3600}
    )
    respx.get("https://api.spotify.com/v1/tracks/0VjIjW4GlUZAMYd2vXMi3b").respond(404)
    resolver = SpotifyResolver("id", "secret")
    with pytest.raises(ResolveError, match="not found"):
        await resolver.resolve(TRACK_URL)
    await resolver.aclose()
