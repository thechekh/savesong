# The matching engine

Spotify never provides audio — SaveSong treats it as a **metadata source** and finds the
actual audio on YouTube Music. For every Spotify track, the pipeline runs a YT Music
search (`ytmusicsearch5`: the first 5 results of a `music.youtube.com/search` extraction,
with a plain `ytsearch5:` fallback) and scores each candidate with pure functions in
[`savesong/core/matcher.py`](../src/savesong/core/matcher.py).

Instead of trusting "first search result", every candidate gets a composite score in
`[0, 1]`:

| weight | component | detail |
|---:|---|---|
| 0.45 | title similarity | `fuzz.token_set_ratio(norm(track.title), norm(cand.title))` |
| 0.30 | artist similarity | best ratio of any track artist vs the channel **and** the candidate title; ` - Topic`/`VEVO` suffixes stripped; a space-stripped comparison catches camelcase channels like `PortalFramesVEVO` |
| 0.15 | duration proximity | 1.0 at \|Δ\| ≤ 3 s, linear falloff to 0.0 at 15 s; 0.5 (neutral) when either side is unknown |
| 0.10 | bonuses | topic channel **+0.6**, "official audio" **+0.4**; rendition keywords (`live`, `cover`, `remix`, `sped up`, `slowed`, `reverb`, `nightcore`, `karaoke`, `instrumental`, `8d audio`, `acoustic`, `reaction`) **−0.5 each** — *unless the source title itself contains the keyword*, so a remix playlist still matches remixes |

`norm()` strips parenthetical noise (`[Remastered 2011]`, `(Deluxe)`) and `feat./ft.`
tails, lowercases, removes punctuation, and collapses whitespace. Note that `with` is
deliberately **not** a feat-marker ("Dancing with the Stars" stays intact).

## Threshold and review

The best candidate is accepted only when its score reaches `match_threshold`
(default **0.72**, configurable via `SAVESONG_MATCH_THRESHOLD` / `match_threshold`).
Below that, the track is marked **`needs_review`** — nothing is downloaded and the
top-3 scored candidates are stored in the library so `savesong review` can offer an
interactive pick later. Guessing wrong costs more than asking.

## Measured accuracy

The matcher is evaluated against a labeled fixture set:
[`tests/fixtures/labeled_matches.json`](../tests/fixtures/labeled_matches.json) —
50 tracks, each with a known-correct video id buried among realistic decoys
(official music videos with different runtimes, live versions, covers, remixes,
sped-up/slowed re-uploads, nightcore, karaoke/instrumentals, same-title tracks by
different artists, extended mixes, hour-long loops). Edge cases include remix-*is*-correct
sources, a live-album track, unicode titles (JP/FR/NL), and multi-artist features.

| metric | value | CI gate |
|---|---:|---:|
| cases | 50 | — |
| top-1 accuracy | **1.000** (50/50) | ≥ 0.88 |
| top-3 accuracy | 1.000 (50/50) | — |
| false `needs_review` flags at 0.72 | 0 | — |

Reproduce with:

```bash
uv run python scripts/eval_matcher.py --verbose
```

The regression gate lives in
[`tests/unit/test_matcher.py`](../tests/unit/test_matcher.py) (`test_labeled_fixture_accuracy_gate`)
and fails the suite if top-1 accuracy drops below **0.88**, so scoring tweaks can't
silently regress.

### Honest caveats

- The fixture set is **synthetic** (hand-authored from real-world failure patterns, with
  fabricated video ids so the repo references no real uploads). Live search results are
  noisier: expect real-world top-1 below the fixture number — that is exactly what the
  review queue is for.
- Popularity (`view_count`) is deliberately **not** scored; it correlates with music
  videos and viral re-uploads, not with the studio recording.
- ISRC is carried on `TrackMeta` but unused for now — YT Music search results don't
  expose it. It's reserved for a future exact-match fast path.

## Tuning

Weights and penalty vocabulary are module constants. The intended workflow:

1. Add a failing real-world case to `labeled_matches.json` (anonymize the video ids).
2. Run `scripts/eval_matcher.py --verbose` and adjust weights/keywords.
3. The CI gate keeps the rest of the set from regressing.
