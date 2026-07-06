"""Shared fixtures: environment isolation, offline yt-dlp fakes, fake arq redis.

Zero network anywhere — Spotify is respx-mocked per test, yt-dlp is replaced by
FakeYDL (copies the CC0 fixture and fires progress hooks), and web tests run on
fakeredis.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

from savesong.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Tests must never see the developer's real config/env."""
    for var in (
        "SAVESONG_MUSIC_DIR",
        "SAVESONG_DB_PATH",
        "SAVESONG_FORMAT",
        "SAVESONG_CONCURRENCY",
        "SAVESONG_MATCH_THRESHOLD",
        "SAVESONG_WEB_PORT",
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
        "REDIS_URL",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("SAVESONG_CONFIG", str(tmp_path / "no-such-config.toml"))


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def sample_opus() -> Path:
    return FIXTURES / "audio" / "cc_sample.opus"


@pytest.fixture
def sample_mp3() -> Path:
    return FIXTURES / "audio" / "cc_sample.mp3"


@pytest.fixture
def cover_png() -> bytes:
    return (FIXTURES / "cover.png").read_bytes()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        music_dir=tmp_path / "music",
        db_path=tmp_path / "data" / "savesong.db",
        concurrency=3,
    )


@pytest.fixture
def spotify_fx() -> dict[str, Any]:
    return json.loads((FIXTURES / "spotify_playlist.json").read_text(encoding="utf-8"))


@pytest.fixture
def ytm_search_fx() -> dict[str, Any]:
    return json.loads((FIXTURES / "ytm_search_results.json").read_text(encoding="utf-8"))


# --- fake yt-dlp -------------------------------------------------------------


class ConcurrencyProbe:
    """Tracks the maximum number of concurrent FakeYDL downloads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.current = 0
        self.max_seen = 0

    def enter(self) -> None:
        with self._lock:
            self.current += 1
            self.max_seen = max(self.max_seen, self.current)

    def exit(self) -> None:
        with self._lock:
            self.current -= 1


class FakeYDL:
    """Offline stand-in for yt_dlp.YoutubeDL.

    "Downloads" by copying the CC0 opus fixture into the engine's staging dir
    and fires realistic progress hooks. Hook exceptions propagate, mirroring
    yt-dlp's abort behaviour.
    """

    def __init__(
        self,
        opts: dict[str, Any],
        source: Path,
        fail_ids: frozenset[str],
        delay: float,
        probe: ConcurrencyProbe | None,
    ) -> None:
        self.opts = opts
        self.source = source
        self.fail_ids = fail_ids
        self.delay = delay
        self.probe = probe

    def __enter__(self) -> FakeYDL:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def extract_info(self, url: str, download: bool = True) -> dict[str, Any] | None:
        video_id = url.rstrip("/").rsplit("=", 1)[-1].rsplit("/", 1)[-1]
        hooks = self.opts.get("progress_hooks") or []
        if self.probe:
            self.probe.enter()
        try:
            total = 1000
            for got in (250, 500, 750):
                for hook in hooks:
                    hook(
                        {
                            "status": "downloading",
                            "downloaded_bytes": got,
                            "total_bytes": total,
                            "speed": 1048576.0,
                        }
                    )
                if self.delay:
                    time.sleep(self.delay)
            if video_id in self.fail_ids:
                raise RuntimeError(f"simulated download failure for {video_id}")
            outtmpl = str(self.opts["outtmpl"])
            path = Path(outtmpl.replace("%(id)s", video_id).replace("%(ext)s", "opus"))
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.source, path)
            for hook in hooks:
                hook({"status": "finished", "filename": str(path)})
            return {
                "id": video_id,
                "ext": "opus",
                "requested_downloads": [{"filepath": str(path)}],
            }
        finally:
            if self.probe:
                self.probe.exit()


def make_fake_ydl_factory(
    source: Path,
    *,
    fail_ids: frozenset[str] = frozenset(),
    delay: float = 0.0,
    probe: ConcurrencyProbe | None = None,
) -> Any:
    def factory(opts: dict[str, Any]) -> FakeYDL:
        return FakeYDL(opts, source, fail_ids, delay, probe)

    return factory


@pytest.fixture
def fake_ydl_factory(sample_opus: Path) -> Any:
    return make_fake_ydl_factory(sample_opus)


# --- fake cover fetch ---------------------------------------------------------


@pytest.fixture
def fake_fetch(cover_png: bytes) -> Any:
    async def fetch(url: str) -> tuple[bytes, str] | None:
        return cover_png, "image/png"

    return fetch


# --- fake arq redis -----------------------------------------------------------


@pytest.fixture
async def arq_redis() -> AsyncIterator[Any]:
    from arq.connections import ArqRedis
    from fakeredis import FakeServer
    from redis.asyncio import ConnectionPool

    try:
        from fakeredis.aioredis import FakeAsyncRedisConnection as FakeConn
    except ImportError:  # older fakeredis
        from fakeredis.aioredis import FakeConnection as FakeConn

    pool = ConnectionPool(connection_class=FakeConn, server=FakeServer())
    redis = ArqRedis(connection_pool=pool)
    try:
        yield redis
    finally:
        await redis.aclose()


# --- misc helpers ---------------------------------------------------------------


@pytest.fixture
def anyio_sleep_none() -> Iterator[None]:
    yield


async def wait_for(predicate: Any, timeout: float = 5.0, interval: float = 0.05) -> None:
    """Poll an async predicate until truthy or time out."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return
        await asyncio.sleep(interval)
    raise TimeoutError("condition not met in time")
