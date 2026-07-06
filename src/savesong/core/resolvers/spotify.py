"""Spotify Web API resolver (metadata only — audio always comes from YT Music).

Uses the client-credentials flow via httpx; public playlists/tracks only,
no user OAuth. The httpx client is injectable for tests (respx).
"""

from __future__ import annotations

import time
from typing import Any, ClassVar

import httpx

from savesong.core.resolvers.base import Resolver
from savesong.core.resolvers.detect import detect
from savesong.errors import ResolveError, SpotifyAuthError
from savesong.models import PlaylistMeta, Resolved, Source, TrackMeta

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"
PAGE_LIMIT = 100


class SpotifyResolver(Resolver):
    source: ClassVar[Source] = "spotify"

    def __init__(
        self,
        client_id: str | None,
        client_secret: str | None,
        *,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http
        self._owns_http = http is None
        self._token: str | None = None
        self._token_expires_at = 0.0

    async def resolve(self, url: str) -> Resolved:
        if not self._client_id or not self._client_secret:
            raise SpotifyAuthError(
                "Spotify credentials required — set SPOTIFY_CLIENT_ID / "
                "SPOTIFY_CLIENT_SECRET or add them via `savesong config init`"
            )
        detected = detect(url)
        if detected.kind == "track":
            data = await self._get(f"/tracks/{detected.external_id}")
            track = _track_meta(data)
            if track is None:
                raise ResolveError(f"Spotify returned an unplayable track for {url}")
            return Resolved(playlist=None, tracks=[track])
        return await self._resolve_playlist(detected.external_id, detected.url)

    async def _resolve_playlist(self, playlist_id: str, url: str) -> Resolved:
        head = await self._get(
            f"/playlists/{playlist_id}", params={"fields": "id,name,external_urls"}
        )
        tracks: list[TrackMeta] = []
        offset = 0
        while True:
            page = await self._get(
                f"/playlists/{playlist_id}/tracks",
                params={"limit": PAGE_LIMIT, "offset": offset},
            )
            for item in page.get("items") or []:
                track = _track_meta((item or {}).get("track"))
                if track is not None:
                    tracks.append(track)
            if not page.get("next"):
                break
            offset += PAGE_LIMIT
        playlist = PlaylistMeta(
            source="spotify",
            external_id=str(head.get("id") or playlist_id),
            title=str(head.get("name") or "Spotify Playlist"),
            url=url,
            tracks=tracks,
        )
        return Resolved(playlist=playlist, tracks=tracks)

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    # -- HTTP plumbing -------------------------------------------------------

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(20.0))
        return self._http

    async def _ensure_token(self) -> str:
        if self._token is not None and time.monotonic() < self._token_expires_at:
            return self._token
        assert self._client_id is not None and self._client_secret is not None
        resp = await self._client().post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
        )
        if resp.status_code in (400, 401, 403):
            raise SpotifyAuthError(f"Spotify rejected the credentials (HTTP {resp.status_code})")
        if resp.status_code != 200:
            raise ResolveError(f"Spotify token endpoint failed (HTTP {resp.status_code})")
        payload = resp.json()
        token = str(payload.get("access_token") or "")
        if not token:
            raise SpotifyAuthError("Spotify token response contained no access_token")
        self._token = token
        self._token_expires_at = time.monotonic() + float(payload.get("expires_in") or 3600) - 60
        return token

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        token = await self._ensure_token()
        resp = await self._client().get(
            f"{API_BASE}{path}", params=params, headers={"Authorization": f"Bearer {token}"}
        )
        if resp.status_code == 401:
            # token expired server-side — refresh once and retry
            self._token = None
            token = await self._ensure_token()
            resp = await self._client().get(
                f"{API_BASE}{path}", params=params, headers={"Authorization": f"Bearer {token}"}
            )
        if resp.status_code == 403:
            raise SpotifyAuthError(
                f"Spotify refused access (HTTP 403): {_error_detail(resp)} — "
                "note: Spotify requires the app owner to have a Premium subscription "
                "for Web API access in development mode"
            )
        if resp.status_code == 404:
            raise ResolveError(f"Spotify resource not found: {path}")
        if resp.status_code != 200:
            raise ResolveError(f"Spotify API error {resp.status_code} for {path}")
        data: dict[str, Any] = resp.json()
        return data


def _error_detail(resp: httpx.Response) -> str:
    """Best-effort human message from a Spotify error body (JSON or plain text)."""
    try:
        payload = resp.json()
        message = str((payload.get("error") or {}).get("message") or "")
    except ValueError:
        message = ""
    return message or resp.text[:200].strip() or "forbidden"


def _track_meta(track: dict[str, Any] | None) -> TrackMeta | None:
    """Map one Spotify track object; None for local files / removed tracks."""
    if not track or track.get("is_local") or not track.get("id"):
        return None
    album = track.get("album") or {}
    images = album.get("images") or []
    cover_url = images[0].get("url") if images else None
    release_year: int | None = None
    release_date = album.get("release_date")
    if isinstance(release_date, str) and len(release_date) >= 4 and release_date[:4].isdigit():
        release_year = int(release_date[:4])
    return TrackMeta(
        source="spotify",
        external_id=str(track["id"]),
        title=str(track.get("name") or "Unknown Title"),
        artists=[str(a.get("name")) for a in track.get("artists") or [] if a.get("name")],
        album=album.get("name"),
        duration_ms=track.get("duration_ms"),
        isrc=(track.get("external_ids") or {}).get("isrc"),
        cover_url=cover_url,
        track_number=track.get("track_number"),
        release_year=release_year,
    )
