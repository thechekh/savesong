# SaveSong — Multi-Source Playlist Downloader (CLI + self-hosted web)

**Pitch:** A clean-room, modern rebuild of your playlist-downloader idea (the `spotify download/` folder is a clone of the GPL project *downtify* — zero portfolio value as-is, and deriving from it forces GPL; SaveSong is written from scratch under MIT). One typed Python engine, two frontends: a beautiful **Typer + Rich CLI** and a small self-hosted **web UI with live SSE progress**. It ingests playlists from **Spotify** (metadata via Web API, audio matched on YouTube Music with a fuzzy scoring engine), **SoundCloud**, and **YouTube Music** (direct via yt-dlp), then tags files with full metadata + cover art, maintains a local SQLite library with dedupe/resume, and exports `.m3u8`. For personal archiving of content you have rights to.

## Tech stack

| Technology | Version | Why |
|---|---|---|
| Python | 3.12 | Single async engine |
| **yt-dlp** | latest (date-versioned) | Audio extraction: YouTube Music, SoundCloud |
| Spotify Web API (httpx client-credentials) | httpx ≥0.28 | Playlist/track metadata + cover art — no SDK bloat, no user OAuth needed |
| **rapidfuzz** | ≥3.11 | Match scoring: title/artist fuzzy + duration window + official-audio boost |
| mutagen | ≥1.47 | ID3/MP4/Vorbis tagging + embedded cover art |
| **Typer + Rich** | ≥0.15 / ≥13.9 | CLI with live multi-track progress bars (asciinema GIF material) |
| FastAPI + SSE | ≥0.115 | Web mode: queue API + live progress stream |
| **arq** + Redis | ≥0.26 / 7.4 | Modern asyncio job queue for web mode (deliberate contrast to Celery elsewhere) |
| SQLAlchemy 2 async + **aiosqlite** | ≥2.0.36 / ≥0.20 | Local library DB — right-sized tool choice (no Postgres for a local app) |
| React 19 + Vite + Tailwind 4 | TS 5.7 | Minimal 2-page SPA: queue + library |
| ffmpeg | 7 (container/system) | Format conversion (opus/m4a → mp3 optional) |
| Docker Compose, uv, ruff, mypy, pytest + respx | latest | Web mode one-command; CLI installs via `uv tool install` |

## Skills it demonstrates (mapped to job requirements)

- **Async Python craftsmanship** — bounded-concurrency download engine (TaskGroup + semaphores), cancellation, resume, progress plumbing from yt-dlp hooks → Rich/SSE
- **Library-first architecture** — one core engine, two delivery mechanisms (CLI + web), the "how do you structure a Python project" interview answer
- **Practical matching/heuristics** — scoring pipeline with tests (the same shape as search relevance work)
- **Modern tooling** — uv-native packaging, arq, SSE, right-sized SQLite choice
- **Judgment** — clean-room rewrite with licensing awareness (great story: "I studied a GPL tool, then designed my own architecture under MIT")

## Estimated build time & difficulty

- **MVP (CLI, all 3 sources):** 1–2 weeks part-time · **Polished (web UI, sync mode, docs):** 3 weeks
- **Difficulty:** Medium (fun-project energy, senior-grade internals)

## What makes it stand out

1. The **matcher** — a documented, tested scoring engine (fuzzy title/artist + duration ±3s + channel heuristics) instead of "first search result"; includes an accuracy table on a labeled fixture set.
2. Rich CLI with parallel live progress bars — instantly impressive in a README GIF.
3. Dual-frontend architecture over one engine; arq shows you know the modern async alternative to Celery.
4. Honest legal posture (personal-use disclaimer, CC-licensed test fixtures, no credentials shipped) — maturity signal, not a liability.
