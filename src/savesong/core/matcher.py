"""Scoring engine that matches a Spotify track to YouTube Music search candidates.

Pure functions, no IO. The weights and the design rationale are documented in
``docs/matching.md``; accuracy is measured against
``tests/fixtures/labeled_matches.json`` and gated in CI.

    score = 0.45 * title similarity        (token_set_ratio on normalized titles)
          + 0.30 * artist similarity       (best artist vs channel / candidate title)
          + 0.15 * duration proximity      (1.0 at |delta| <= 3s, linear to 0 at 15s)
          + 0.10 * bonuses                 (topic/official-audio +, live/cover/remix/... -)

If the best score is below ``match_threshold`` the track is marked
``needs_review`` (top-3 candidates stored) instead of guessing.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from savesong.models import MatchCandidate, MatchResult, ScoredCandidate, TrackMeta

TITLE_WEIGHT = 0.45
ARTIST_WEIGHT = 0.30
DURATION_WEIGHT = 0.15
BONUS_WEIGHT = 0.10

DEFAULT_THRESHOLD = 0.72

DURATION_EXACT_S = 3.0
DURATION_ZERO_S = 15.0

PENALTY_WORDS: tuple[str, ...] = (
    "live",
    "cover",
    "remix",
    "sped up",
    "slowed",
    "reverb",
    "nightcore",
    "karaoke",
    "instrumental",
    "8d audio",
    "acoustic",
    "reaction",
)

_PAREN_RE = re.compile(r"[(\[{][^)\]}]*[)\]}]")
_FEAT_RE = re.compile(r"\b(?:feat|ft|featuring)\b\.?.*$", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_TOPIC_RE = re.compile(r"\s*-\s*topic\s*$", re.IGNORECASE)
_VEVO_RE = re.compile(r"vevo\s*$", re.IGNORECASE)


def norm(text: str) -> str:
    """Normalize a title for fuzzy comparison.

    Strips parenthetical noise and feat./ft. tails, lowercases, removes
    punctuation, collapses whitespace.
    """
    t = _PAREN_RE.sub(" ", text)
    t = _FEAT_RE.sub(" ", t)
    t = t.lower()
    t = _PUNCT_RE.sub(" ", t)
    return _WS_RE.sub(" ", t).strip()


def duration_score(track_ms: int | None, cand_s: int | None) -> float:
    """1.0 within +/-3s, linear falloff to 0.0 at 15s; 0.5 (neutral) when unknown."""
    if track_ms is None or cand_s is None:
        return 0.5
    delta = abs(track_ms / 1000.0 - float(cand_s))
    if delta <= DURATION_EXACT_S:
        return 1.0
    if delta >= DURATION_ZERO_S:
        return 0.0
    return (DURATION_ZERO_S - delta) / (DURATION_ZERO_S - DURATION_EXACT_S)


def artist_score(track: TrackMeta, cand: MatchCandidate) -> float:
    """Best fuzzy ratio of any source artist against the channel and candidate title."""
    channel = _VEVO_RE.sub("", _TOPIC_RE.sub("", cand.channel))
    fields = [f for f in (norm(channel), norm(cand.title)) if f]
    if not fields:
        return 0.0
    best = 0.0
    for artist in track.artists:
        a = norm(artist)
        if not a:
            continue
        compact_artist = a.replace(" ", "")
        for field in fields:
            best = max(best, fuzz.token_set_ratio(a, field) / 100.0)
            # camelcase channels like "PortalFramesVEVO" defeat token matching
            compact_field = field.replace(" ", "")
            if compact_artist and compact_field:
                best = max(best, fuzz.ratio(compact_artist, compact_field) / 100.0)
    return best


def bonus_score(track: TrackMeta, cand: MatchCandidate) -> float:
    """Signed sub-score in [-1, 1].

    Topic channels / "official audio" uploads are boosted; rendition keywords
    (live, cover, remix, sped up, ...) are penalized unless the source title
    itself contains them.
    """
    b = 0.0
    cand_title = cand.title.lower()
    src_title = track.title.lower()
    if _TOPIC_RE.search(cand.channel):
        b += 0.6
    if "official audio" in cand_title:
        b += 0.4
    for word in PENALTY_WORDS:
        if word in cand_title and word not in src_title:
            b -= 0.5
    return max(-1.0, min(1.0, b))


def score(track: TrackMeta, cand: MatchCandidate) -> float:
    """Composite match score in [0, 1]."""
    title_part = fuzz.token_set_ratio(norm(track.title), norm(cand.title)) / 100.0
    total = (
        TITLE_WEIGHT * title_part
        + ARTIST_WEIGHT * artist_score(track, cand)
        + DURATION_WEIGHT * duration_score(track.duration_ms, cand.duration_s)
        + BONUS_WEIGHT * bonus_score(track, cand)
    )
    return max(0.0, min(1.0, total))


def pick(
    track: TrackMeta,
    candidates: list[MatchCandidate],
    threshold: float = DEFAULT_THRESHOLD,
) -> MatchResult:
    """Score all candidates and pick the best; below-threshold means needs_review."""
    scored = sorted(
        (ScoredCandidate(candidate=c, score=score(track, c)) for c in candidates),
        key=lambda s: s.score,
        reverse=True,
    )
    if not scored:
        return MatchResult(best=None, score=0.0, needs_review=True, top=[])
    best = scored[0]
    return MatchResult(
        best=best.candidate,
        score=best.score,
        needs_review=best.score < threshold,
        top=scored[:3],
    )
