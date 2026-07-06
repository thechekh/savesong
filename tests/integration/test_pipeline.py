"""Full offline pipeline runs: resolve → match → download → tag → record → m3u."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from savesong.config import Settings
from savesong.core.library import Library
from savesong.core.pipeline import Pipeline
from savesong.models import JobProgress, MatchCandidate
from tests.conftest import make_fake_ydl_factory
from tests.integration.test_resolver_spotify import PLAYLIST_URL, install_routes

SC_URL = "https://soundcloud.com/dj-orbit/sets/late-night-mix"


def topic_candidates(query: str) -> list[MatchCandidate]:
    """Synthesize a perfect topic-channel candidate for '<artist> <title>' queries."""
    artist = query.split(" ")[0] + " " + query.split(" ")[1]  # two-word artists in fixtures
    return [
        MatchCandidate(
            video_id=f"v{abs(hash(query)) % 10**10:010d}",
            title=query.removeprefix(artist).strip() or query,
            channel=f"{artist} - Topic",
            duration_s=214,
        )
    ]


class SearchMap:
    """Deterministic YT Music search stub keyed by track title keywords."""

    def __init__(self, mapping: dict[str, list[MatchCandidate]]) -> None:
        self.mapping = mapping
        self.queries: list[str] = []

    async def __call__(self, query: str) -> list[MatchCandidate]:
        self.queries.append(query)
        for needle, candidates in self.mapping.items():
            if needle.lower() in query.lower():
                return candidates
        return []


def spotify_search_map() -> SearchMap:
    good1 = MatchCandidate(
        video_id="ytneon00001",
        title="Neon Coastline",
        channel="Portal Frames - Topic",
        duration_s=214,
    )
    good2 = MatchCandidate(
        video_id="ytchrome001",
        title="Chrome Sunset",
        channel="Portal Frames - Topic",
        duration_s=188,
    )
    junk = [
        MatchCandidate(
            video_id="junk0000001",
            title="Completely Different Song (Live)",
            channel="someone else",
            duration_s=520,
        )
    ]
    return SearchMap({"Neon Coastline": [good1], "Chrome Sunset": [good2], "Analog Hearts": junk})


@pytest.fixture
def sc_extract() -> Any:
    from tests.integration.test_resolvers_ytdlp import SC_SET

    async def extract(url: str) -> dict[str, Any]:
        return SC_SET

    return extract


@respx.mock
async def test_spotify_playlist_end_to_end(
    settings: Settings,
    spotify_fx: dict[str, Any],
    sample_opus: Path,
    fake_fetch: Any,
    cover_png: bytes,
) -> None:
    install_routes(spotify_fx)
    creds = settings.model_copy(
        update={"spotify_client_id": "id", "spotify_client_secret": "secret"}
    )
    events: list[JobProgress] = []
    search = spotify_search_map()

    async with Library(creds.resolved_db_path) as library:
        pipeline = Pipeline(
            creds,
            library,
            emit=events.append,
            ydl_factory=make_fake_ydl_factory(sample_opus),
            search=search,
            fetch=fake_fetch,
        )
        summary = await pipeline.run_url(PLAYLIST_URL)
        await pipeline.aclose()

        assert summary.total == 3
        assert summary.downloaded == 2
        assert summary.needs_review == 1
        assert summary.failed == 0 and summary.skipped == 0

        # files organized {artist}/{album}/{nn} - {title}.{ext}
        f1 = creds.music_dir / "Portal Frames" / "Night Drive OST" / "01 - Neon Coastline.opus"
        f2 = (
            creds.music_dir
            / "Portal Frames"
            / "Night Drive OST"
            / "04 - Chrome Sunset (feat. Vela Ray).opus"
        )
        assert f1.exists() and f2.exists()

        # tagged with metadata + embedded cover
        import base64

        from mutagen.flac import Picture
        from mutagen.oggopus import OggOpus

        audio = OggOpus(str(f1))
        assert audio["title"] == ["Neon Coastline"]
        assert audio["artist"] == ["Portal Frames"]
        assert audio["album"] == ["Night Drive OST"]
        pic = Picture(base64.b64decode(audio["metadata_block_picture"][0]))
        assert pic.data == cover_png

        # m3u8 written next to the library root
        m3u = creds.music_dir / "Synthwave Essentials.m3u8"
        assert m3u.exists()
        content = m3u.read_text(encoding="utf-8")
        assert str(f1) in content and str(f2) in content

        # db state: 2 done, 1 needs_review with stored top-3 json
        stats = await library.stats()
        assert stats["done"] == 2 and stats["needs_review"] == 1
        review_rows = await library.needs_review_tracks()
        assert len(review_rows) == 1
        stored = json.loads(review_rows[0].match_candidates or "[]")
        assert stored and stored[0]["video_id"] == "junk0000001"

        # events: running state with total, per-track progress, track_done, job_done
        kinds = [e.event for e in events]
        assert kinds[0] == "state"
        assert any(e.event == "state" and e.total == 3 for e in events)
        assert any(e.event == "progress" and (e.pct or 0) > 0 for e in events)
        assert sum(1 for e in events if e.event == "track_done") == 3
        assert kinds[-1] == "job_done"
        assert events[-1].summary is not None and events[-1].summary.downloaded == 2


@respx.mock
async def test_rerun_skips_everything_downloaded(
    settings: Settings, spotify_fx: dict[str, Any], sample_opus: Path, fake_fetch: Any
) -> None:
    install_routes(spotify_fx)
    creds = settings.model_copy(
        update={"spotify_client_id": "id", "spotify_client_secret": "secret"}
    )
    async with Library(creds.resolved_db_path) as library:

        def build() -> Pipeline:
            return Pipeline(
                creds,
                library,
                ydl_factory=make_fake_ydl_factory(sample_opus),
                search=spotify_search_map(),
                fetch=fake_fetch,
            )

        first = await build().run_url(PLAYLIST_URL)
        assert first.downloaded == 2
        second = await build().run_url(PLAYLIST_URL)
        assert second.downloaded == 0
        assert second.skipped == 2
        assert second.needs_review == 1  # still waiting on review, not re-guessed


@respx.mock
async def test_failed_track_retries_with_stored_match(
    settings: Settings, spotify_fx: dict[str, Any], sample_opus: Path, fake_fetch: Any
) -> None:
    install_routes(spotify_fx)
    creds = settings.model_copy(
        update={"spotify_client_id": "id", "spotify_client_secret": "secret"}
    )
    async with Library(creds.resolved_db_path) as library:
        failing = Pipeline(
            creds,
            library,
            ydl_factory=make_fake_ydl_factory(sample_opus, fail_ids=frozenset({"ytneon00001"})),
            search=spotify_search_map(),
            fetch=fake_fetch,
        )
        first = await failing.run_url(PLAYLIST_URL)
        assert first.failed == 1 and first.downloaded == 1

        failed_rows = await library.failed_tracks()
        assert len(failed_rows) == 1
        assert failed_rows[0].matched_video_id == "ytneon00001"

        healthy = Pipeline(
            creds,
            library,
            ydl_factory=make_fake_ydl_factory(sample_opus),
            search=spotify_search_map(),
            fetch=fake_fetch,
        )
        retried = await healthy.retry_failed()
        assert retried.downloaded == 1
        assert await library.failed_tracks() == []


async def test_soundcloud_set_end_to_end(
    settings: Settings, sample_opus: Path, fake_fetch: Any, sc_extract: Any
) -> None:
    from savesong.core.resolvers.soundcloud import SoundCloudResolver

    async with Library(settings.resolved_db_path) as library:
        pipeline = Pipeline(
            settings,
            library,
            ydl_factory=make_fake_ydl_factory(sample_opus),
            fetch=fake_fetch,
            resolvers={"soundcloud": SoundCloudResolver(extract=sc_extract)},
        )
        summary = await pipeline.run_url(SC_URL)
        assert summary.downloaded == 2 and summary.failed == 0

        f1 = settings.music_dir / "dj-orbit" / "Late Night Mix" / "01 - First Wave.opus"
        assert f1.exists()
        assert (settings.music_dir / "Late Night Mix.m3u8").exists()


async def test_dry_run_downloads_nothing_and_persists_nothing(
    settings: Settings, sample_opus: Path, sc_extract: Any
) -> None:
    from savesong.core.resolvers.soundcloud import SoundCloudResolver

    async with Library(settings.resolved_db_path) as library:
        pipeline = Pipeline(
            settings,
            library,
            ydl_factory=make_fake_ydl_factory(sample_opus),
            resolvers={"soundcloud": SoundCloudResolver(extract=sc_extract)},
        )
        results = await pipeline.dry_run(SC_URL)
        assert [r.status for r in results] == ["matched", "matched"]
        assert not settings.music_dir.exists() or not list(settings.music_dir.rglob("*.opus"))
        assert (await library.stats())["tracks"] == 0


@respx.mock
async def test_spotify_dry_run_shows_match_scores(
    settings: Settings, spotify_fx: dict[str, Any]
) -> None:
    install_routes(spotify_fx)
    creds = settings.model_copy(
        update={"spotify_client_id": "id", "spotify_client_secret": "secret"}
    )
    async with Library(creds.resolved_db_path) as library:
        pipeline = Pipeline(creds, library, search=spotify_search_map())
        results = await pipeline.dry_run(PLAYLIST_URL)
        by_title = {r.track.title: r for r in results}
        assert by_title["Neon Coastline"].status == "matched"
        assert (by_title["Neon Coastline"].match or None) is not None
        assert by_title["Analog Hearts"].status == "needs_review"


async def test_sync_reports_and_prunes_removed_tracks(
    settings: Settings, sample_opus: Path, fake_fetch: Any
) -> None:
    from savesong.core.resolvers.soundcloud import SoundCloudResolver
    from tests.integration.test_resolvers_ytdlp import SC_SET

    state = {"response": SC_SET}

    async def extract(url: str) -> dict[str, Any]:
        return state["response"]

    async with Library(settings.resolved_db_path) as library:

        def build() -> Pipeline:
            return Pipeline(
                settings,
                library,
                ydl_factory=make_fake_ydl_factory(sample_opus),
                fetch=fake_fetch,
                resolvers={"soundcloud": SoundCloudResolver(extract=extract)},
            )

        first, removed = await build().sync_url(SC_URL)
        assert first.downloaded == 2 and removed == []

        shrunk = dict(SC_SET)
        shrunk["entries"] = SC_SET["entries"][:1]
        state["response"] = shrunk

        second, removed = await build().sync_url(SC_URL)
        assert second.skipped == 1
        assert [r.title for r in removed] == ["Second Wave"]
        # not pruned yet
        gone_row = removed[0]
        assert gone_row.file_path and Path(gone_row.file_path).exists()

        third, removed = await build().sync_url(SC_URL, prune=True)
        assert [r.title for r in removed] == ["Second Wave"]
        assert not Path(str(gone_row.file_path)).exists()
        assert await library.get_track(gone_row.id) is None


@respx.mock
async def test_resolve_error_propagates(settings: Settings) -> None:
    respx.post("https://accounts.spotify.com/api/token").mock(
        side_effect=httpx.ConnectError("no network")
    )
    creds = settings.model_copy(
        update={"spotify_client_id": "id", "spotify_client_secret": "secret"}
    )
    async with Library(creds.resolved_db_path) as library:
        pipeline = Pipeline(creds, library)
        with pytest.raises(httpx.ConnectError):
            await pipeline.run_url(PLAYLIST_URL)
