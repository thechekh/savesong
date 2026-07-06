"""Evaluate the matcher against tests/fixtures/labeled_matches.json.

Prints per-case outcomes and the headline numbers used in docs/matching.md.
Run: uv run python scripts/eval_matcher.py [--verbose]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from savesong.core import matcher
from savesong.models import MatchCandidate, TrackMeta

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "labeled_matches.json"


def main() -> int:
    verbose = "--verbose" in sys.argv
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    top1 = 0
    top3 = 0
    review_flags = 0
    misses: list[str] = []
    for case in cases:
        track = TrackMeta(source="spotify", external_id="x", **case["track"])
        candidates = [MatchCandidate(**c) for c in case["candidates"]]
        result = matcher.pick(track, candidates)
        correct = case["correct_video_id"]
        picked = result.best.video_id if result.best else None
        in_top3 = any(sc.candidate.video_id == correct for sc in result.top)
        top1 += picked == correct
        top3 += in_top3
        review_flags += result.needs_review
        mark = "ok " if picked == correct else "MISS"
        if verbose or picked != correct:
            line = (
                f"[{mark}] {track.artist_display} - {track.title!r}: picked={picked} "
                f"score={result.score:.3f} review={result.needs_review}"
            )
            print(line)
        if picked != correct:
            misses.append(track.title)
    n = len(cases)
    print(f"\ncases:          {n}")
    print(f"top-1 accuracy: {top1 / n:.3f} ({top1}/{n})")
    print(f"top-3 accuracy: {top3 / n:.3f} ({top3}/{n})")
    print(f"needs_review:   {review_flags} flagged at threshold {matcher.DEFAULT_THRESHOLD}")
    if misses:
        print(f"misses: {', '.join(misses)}")
    return 0 if top1 / n >= 0.88 else 1


if __name__ == "__main__":
    raise SystemExit(main())
