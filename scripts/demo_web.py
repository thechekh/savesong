"""Serve the built SPA + API on one port — no docker, no real Redis.

Seeds the demo library into a temp sandbox, fakes Redis in-process, mounts
``web/dist`` as static files, and runs uvicorn. Used for UI screenshots and
quick frontend poking.

    npm --prefix web run build          # once
    uv run python scripts/demo_web.py   # → http://127.0.0.1:8765
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from savesong.config import Settings
from savesong.core.library import Library
from savesong.db.seed import seed
from savesong.web.app import create_app

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "dist"


def make_fake_redis() -> Any:
    from arq.connections import ArqRedis
    from fakeredis import FakeServer
    from redis.asyncio import ConnectionPool

    try:
        from fakeredis.aioredis import FakeAsyncRedisConnection as FakeConn
    except ImportError:  # older fakeredis
        from fakeredis.aioredis import FakeConnection as FakeConn

    return ArqRedis(connection_pool=ConnectionPool(connection_class=FakeConn, server=FakeServer()))


async def build_app() -> FastAPI:
    sandbox = Path(tempfile.mkdtemp(prefix="savesong-web-demo-"))
    settings = Settings(music_dir=sandbox / "music", db_path=sandbox / "demo.db")
    await seed(settings)

    library = await Library(settings.resolved_db_path).open()
    # a few illustrative jobs so the Queue tab isn't empty
    await library.create_job("demo-done", "https://soundcloud.com/portal-frames/sets/night-drive")
    await library.update_job(
        "demo-done", state="done", total=6, completed=6, finished_at="2026-07-06T11:58:00+00:00"
    )
    await library.create_job(
        "demo-running", "https://open.spotify.com/playlist/5FpYt2XoNbXvJp0k4v3Kx1"
    )
    await library.update_job("demo-running", state="running", total=12, completed=5)
    await library.create_job("demo-failed", "https://music.youtube.com/playlist?list=OLAK5uy_demo")
    await library.update_job(
        "demo-failed",
        state="failed",
        total=4,
        completed=3,
        failed=1,
        finished_at="2026-07-06T11:41:00+00:00",
    )

    app = create_app(settings, redis=make_fake_redis(), library=library)
    if not DIST.exists():
        raise SystemExit("web/dist missing — run `npm --prefix web run build` first")
    app.mount("/", StaticFiles(directory=DIST, html=True), name="spa")
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    app = asyncio.run(build_app())
    print(f"SaveSong demo UI → http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
