"""Matcher unit tests + the labeled-fixture accuracy gate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from savesong.core import matcher
from savesong.models import MatchCandidate, TrackMeta


def track(
    title: str = "Song Title",
    artists: tuple[str, ...] = ("Some Artist",),
    duration_ms: int | None = 200000,
) -> TrackMeta:
    return TrackMeta(
        source="spotify",
        external_id="t1",
        title=title,
        artists=list(artists),
        duration_ms=duration_ms,
    )


def cand(
    title: str = "Song Title",
    channel: str = "Some Artist - Topic",
    duration_s: int | None = 200,
    video_id: str = "vvvvvvvvvv1",
) -> MatchCandidate:
    return MatchCandidate(video_id=video_id, title=title, channel=channel, duration_s=duration_s)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Song Title", "song title"),
        ("Song Title (feat. Someone)", "song title"),
        ("Song Title feat. Someone", "song title"),
        ("Song Title ft. Someone", "song title"),
        ("Song Title [Remastered 2011]", "song title"),
        ("SONG TITLE!!!", "song title"),
        ("  Song    Title  ", "song title"),
        ("Song - Title", "song title"),
        ("Café Del Mar", "café del mar"),
        ("", ""),
    ],
)
def test_norm(raw: str, expected: str) -> None:
    assert matcher.norm(raw) == expected


def test_norm_keeps_with_phrases() -> None:
    # "with" must not be treated as a feat. marker
    assert matcher.norm("Dancing with the Stars") == "dancing with the stars"


@pytest.mark.parametrize(
    ("track_ms", "cand_s", "expected"),
    [
        (200000, 200, 1.0),
        (200000, 203, 1.0),
        (200000, 197, 1.0),
        (200000, 209, 0.5),
        (200000, 215, 0.0),
        (200000, 400, 0.0),
        (None, 200, 0.5),
        (200000, None, 0.5),
    ],
)
def test_duration_score(track_ms: int | None, cand_s: int | None, expected: float) -> None:
    assert matcher.duration_score(track_ms, cand_s) == pytest.approx(expected, abs=1e-6)


def test_bonus_topic_channel_and_official_audio() -> None:
    assert matcher.bonus_score(track(), cand(channel="Some Artist - Topic")) > 0
    assert matcher.bonus_score(track(), cand(title="Song Title (Official Audio)", channel="x")) > 0


def test_bonus_penalizes_renditions() -> None:
    t = track()
    assert matcher.bonus_score(t, cand(title="Song Title (Live)", channel="x")) < 0
    assert matcher.bonus_score(t, cand(title="Song Title sped up", channel="x")) < 0
    assert matcher.bonus_score(t, cand(title="Song Title (Piano Cover)", channel="x")) < 0


def test_bonus_penalty_waived_when_source_is_that_rendition() -> None:
    live_track = track(title="Song Title (Live at Wembley)")
    assert matcher.bonus_score(live_track, cand(title="Song Title (Live)", channel="x")) >= 0


def test_bonus_clamped() -> None:
    t = track()
    horror = cand(title="Song Title live cover remix nightcore karaoke", channel="x")
    assert matcher.bonus_score(t, horror) == -1.0


def test_artist_score_matches_topic_channel_and_title() -> None:
    t = track(artists=("Portal Frames",))
    assert matcher.artist_score(t, cand(channel="Portal Frames - Topic", title="X")) == 1.0
    assert (
        matcher.artist_score(t, cand(channel="whatever", title="Portal Frames - Song Title")) == 1.0
    )
    assert matcher.artist_score(t, cand(channel="PortalFramesVEVO", title="X")) > 0.5
    assert matcher.artist_score(t, cand(channel="Unrelated Band", title="Nope")) < 0.6


def test_score_prefers_topic_exact_over_rendition() -> None:
    t = track()
    good = cand()
    live = cand(title="Song Title (Live)", channel="Some Artist", duration_s=260)
    assert matcher.score(t, good) > matcher.score(t, live)


def test_score_bounded() -> None:
    t = track()
    assert 0.0 <= matcher.score(t, cand(title="zzz", channel="zzz", duration_s=999)) <= 1.0
    assert 0.0 <= matcher.score(t, cand()) <= 1.0


def test_pick_empty_candidates() -> None:
    result = matcher.pick(track(), [])
    assert result.best is None
    assert result.needs_review is True
    assert result.top == []


def test_pick_below_threshold_flags_review_with_top3() -> None:
    t = track(title="Extremely Specific Song")
    weak = [
        cand(title="Different Thing", channel="a", duration_s=100, video_id="wwwwwwwwww1"),
        cand(title="Another Thing", channel="b", duration_s=110, video_id="wwwwwwwwww2"),
        cand(title="Third Thing", channel="c", duration_s=120, video_id="wwwwwwwwww3"),
        cand(title="Fourth Thing", channel="d", duration_s=130, video_id="wwwwwwwwww4"),
    ]
    result = matcher.pick(t, weak, threshold=0.9)
    assert result.needs_review is True
    assert len(result.top) == 3
    assert result.top[0].score >= result.top[1].score >= result.top[2].score


def test_pick_orders_by_score() -> None:
    t = track()
    good = cand(video_id="ggggggggggg")
    live = cand(
        title="Song Title (Live)", channel="Some Artist", duration_s=280, video_id="lllllllllll"
    )
    result = matcher.pick(t, [live, good])
    assert result.best is not None and result.best.video_id == "ggggggggggg"
    assert result.needs_review is False


def test_labeled_fixture_accuracy_gate() -> None:
    """Regression gate: top-1 accuracy on the labeled set must stay >= 0.88."""
    fixture = Path(__file__).parents[1] / "fixtures" / "labeled_matches.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 50
    hits = 0
    for case in cases:
        t = TrackMeta(source="spotify", external_id="x", **case["track"])
        candidates = [MatchCandidate(**c) for c in case["candidates"]]
        result = matcher.pick(t, candidates)
        if result.best is not None and result.best.video_id == case["correct_video_id"]:
            hits += 1
    accuracy = hits / len(cases)
    assert accuracy >= 0.88, f"matcher top-1 accuracy regressed: {accuracy:.3f}"
