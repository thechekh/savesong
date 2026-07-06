# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `savesong get <url>` with source auto-detection (Spotify, SoundCloud, YouTube Music).
- Spotify pipeline: Web API metadata → YouTube Music candidate search → rapidfuzz scoring
  engine → yt-dlp audio download.
- SoundCloud / YouTube Music direct playlist and track extraction via yt-dlp.
- Bounded-concurrency async download engine with `.part` staging and atomic rename;
  Ctrl-C leaves no partial files.
- Tagging (mutagen): title, artists, album, track number, year, embedded cover art
  for opus / m4a / mp3.
- Organizer: `{artist}/{album or playlist}/{nn} - {title}.{ext}` with cross-platform
  sanitization and collision suffixes.
- SQLite library (SQLAlchemy async + Alembic): dedupe, resume, retry, stats,
  `.m3u8` export.
- CLI: `get`, `sync`, `library list|stats`, `export-m3u`, `retry-failed`, `review`,
  `config init`, `--dry-run`.
- Web mode: FastAPI + arq + Redis job queue, SSE live progress, React 19 SPA
  (queue + library), one-command `docker compose up` with seeded demo library.
- Labeled matcher fixture set (50 tracks) with accuracy gate in CI;
  scoring design documented in `docs/matching.md`.

[Unreleased]: https://github.com/thechekh/savesong/commits/main
