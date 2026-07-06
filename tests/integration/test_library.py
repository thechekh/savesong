"""Library repository: migrations, dedupe, resume, retry queries, jobs."""

from __future__ import annotations

import json
from pathlib import Path

from savesong.config import Settings
from savesong.core.library import Library
from savesong.models import PlaylistMeta, TrackMeta


def playlist_meta(external_id: str = "pl-1", title: str = "Mix") -> PlaylistMeta:
    return PlaylistMeta(
        source="soundcloud", external_id=external_id, title=title, url="https://x/sets/mix"
    )


def track_meta(external_id: str = "tr-1", title: str = "Song") -> TrackMeta:
    return TrackMeta(
        source="soundcloud",
        external_id=external_id,
        title=title,
        artists=["Artist A", "Artist B"],
        album="Mix",
        duration_ms=201000,
        cover_url="https://x/cover.jpg",
    )


async def test_open_is_idempotent_and_migrates(settings: Settings) -> None:
    async with Library(settings.resolved_db_path) as lib1:
        await lib1.upsert_playlist(playlist_meta())
    async with Library(settings.resolved_db_path) as lib2:  # re-open on migrated db
        assert (await lib2.stats())["playlists"] == 1


async def test_upsert_playlist_updates_in_place(settings: Settings) -> None:
    async with Library(settings.resolved_db_path) as lib:
        pid1 = await lib.upsert_playlist(playlist_meta(title="Old Title"))
        pid2 = await lib.upsert_playlist(playlist_meta(title="New Title"))
        assert pid1 == pid2
        row = await lib.get_playlist(pid1)
        assert row is not None and row.title == "New Title"


async def test_upsert_track_dedupes_within_playlist(settings: Settings) -> None:
    async with Library(settings.resolved_db_path) as lib:
        pid = await lib.upsert_playlist(playlist_meta())
        row1 = await lib.upsert_track(track_meta(), pid)
        row2 = await lib.upsert_track(track_meta(title="Renamed"), pid)
        assert row1.id == row2.id
        assert row2.title == "Renamed"
        assert row2.artists_list == ["Artist A", "Artist B"]
        # same external id under no playlist is a separate logical row
        standalone = await lib.upsert_track(track_meta(), None)
        assert standalone.id != row1.id
        standalone_again = await lib.upsert_track(track_meta(), None)
        assert standalone_again.id == standalone.id


async def test_dedupe_requires_file_on_disk(settings: Settings, tmp_path: Path) -> None:
    async with Library(settings.resolved_db_path) as lib:
        pid = await lib.upsert_playlist(playlist_meta())
        row = await lib.upsert_track(track_meta(), pid)
        assert not Library.is_downloaded_row(row)
        audio = tmp_path / "song.opus"
        audio.write_bytes(b"x")
        await lib.mark_done(row.id, audio)
        refreshed = await lib.get_track(row.id)
        assert refreshed is not None and Library.is_downloaded_row(refreshed)
        assert await lib.find_done("soundcloud", "tr-1") is not None
        audio.unlink()  # file vanished → dedupe misses, re-download allowed
        assert await lib.find_done("soundcloud", "tr-1") is None


async def test_status_transitions_and_queries(settings: Settings, tmp_path: Path) -> None:
    async with Library(settings.resolved_db_path) as lib:
        pid = await lib.upsert_playlist(playlist_meta())
        r1 = await lib.upsert_track(track_meta("a", "Alpha"), pid)
        r2 = await lib.upsert_track(track_meta("b", "Beta"), pid)
        r3 = await lib.upsert_track(track_meta("c", "Gamma"), pid)

        await lib.mark_matched(r1.id, "vid00000001", 0.91, json.dumps([]))
        await lib.mark_failed(r2.id, "boom")
        await lib.mark_needs_review(r3.id, 0.4, json.dumps([{"video_id": "x"}]))

        assert [r.id for r in await lib.failed_tracks()] == [r2.id]
        assert [r.id for r in await lib.needs_review_tracks()] == [r3.id]

        got1 = await lib.get_track(r1.id)
        assert got1 is not None
        assert got1.status == "matched"
        assert got1.matched_video_id == "vid00000001"
        assert got1.match_score == 0.91

        audio = tmp_path / "a.opus"
        audio.write_bytes(b"x")
        await lib.mark_done(r1.id, audio)
        done1 = await lib.get_track(r1.id)
        assert done1 is not None and done1.downloaded_at is not None and done1.error is None


async def test_reset_stale_downloading(settings: Settings) -> None:
    async with Library(settings.resolved_db_path) as lib:
        pid = await lib.upsert_playlist(playlist_meta())
        row = await lib.upsert_track(track_meta(), pid)
        await lib.mark_downloading([row.id])
    async with Library(settings.resolved_db_path) as lib:  # reopen triggers reset
        refreshed = await lib.get_track(row.id)
        assert refreshed is not None and refreshed.status == "pending"


async def test_list_library_pagination_and_search(settings: Settings, tmp_path: Path) -> None:
    async with Library(settings.resolved_db_path) as lib:
        pid = await lib.upsert_playlist(playlist_meta())
        for i in range(5):
            row = await lib.upsert_track(track_meta(f"t{i}", f"Track {i}"), pid)
            audio = tmp_path / f"{i}.opus"
            audio.write_bytes(b"x")
            await lib.mark_done(row.id, audio)

        page1, cursor = await lib.list_library(limit=2)
        assert len(page1) == 2 and cursor is not None
        page2, cursor2 = await lib.list_library(cursor=cursor, limit=2)
        assert len(page2) == 2 and cursor2 is not None
        page3, cursor3 = await lib.list_library(cursor=cursor2, limit=2)
        assert len(page3) == 1 and cursor3 is None
        ids = [r.id for r in page1 + page2 + page3]
        assert ids == sorted(ids)

        hits, _ = await lib.list_library(q="Track 3")
        assert [r.title for r in hits] == ["Track 3"]
        by_artist, _ = await lib.list_library(q="artist a")
        assert len(by_artist) == 5


async def test_stats_counts(settings: Settings) -> None:
    async with Library(settings.resolved_db_path) as lib:
        pid = await lib.upsert_playlist(playlist_meta())
        await lib.upsert_track(track_meta("a"), pid)
        r2 = await lib.upsert_track(track_meta("b"), pid)
        await lib.mark_failed(r2.id, "x")
        stats = await lib.stats()
        assert stats["playlists"] == 1
        assert stats["tracks"] == 2
        assert stats["pending"] == 1
        assert stats["failed"] == 1


async def test_delete_track(settings: Settings) -> None:
    async with Library(settings.resolved_db_path) as lib:
        pid = await lib.upsert_playlist(playlist_meta())
        row = await lib.upsert_track(track_meta(), pid)
        await lib.delete_track(row.id)
        assert await lib.get_track(row.id) is None


async def test_jobs_crud(settings: Settings) -> None:
    async with Library(settings.resolved_db_path) as lib:
        await lib.create_job("job-1", "https://soundcloud.com/a/sets/b")
        row = await lib.get_job("job-1")
        assert row is not None and row.state == "queued" and row.created_at

        await lib.update_job("job-1", state="running", total=10)
        await lib.bump_job_counters("job-1", completed=1)
        await lib.bump_job_counters("job-1", completed=1, failed=1)
        row = await lib.get_job("job-1")
        assert row is not None
        assert (row.state, row.total, row.completed, row.failed) == ("running", 10, 2, 1)

        await lib.create_job("job-2", "https://x")
        jobs = await lib.list_jobs()
        assert [j.id for j in jobs][0] in {"job-1", "job-2"}
        assert len(jobs) == 2
