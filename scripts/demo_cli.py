"""Offline, scripted demo of the SaveSong engine — no network, ever.

A fake SoundCloud set is "downloaded" through the real pipeline (engine,
organizer, tagger, SQLite library, m3u export); only yt-dlp and cover fetching
are stubbed with local fixtures. Runs twice to show dedupe/resume.

    uv run python scripts/demo_cli.py                 # asciinema-friendly
    uv run python scripts/demo_cli.py --export-svg docs/images/demo-cli.svg
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from rich.console import Console

from savesong.cli.progress import ProgressUI, render_summary
from savesong.config import Settings
from savesong.core.library import Library
from savesong.core.pipeline import Pipeline
from savesong.core.resolvers.soundcloud import SoundCloudResolver
from savesong.db.seed import solid_png

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "tests" / "fixtures" / "audio" / "cc_sample.opus"
DEMO_URL = "https://soundcloud.com/portal-frames/sets/night-drive-mixtape"

DEMO_SET: dict[str, Any] = {
    "_type": "playlist",
    "id": 424242,
    "title": "Night Drive Mixtape",
    "entries": [
        {"id": 1001, "title": "Neon Coastline", "uploader": "Portal Frames", "duration": 214.0},
        {"id": 1002, "title": "Chrome Sunset", "uploader": "Portal Frames", "duration": 187.0},
        {"id": 1003, "title": "Analog Hearts", "uploader": "Vela Ray", "duration": 243.0},
        {"id": 1004, "title": "Glass Highways", "uploader": "Vela Ray", "duration": 201.0},
        {"id": 1005, "title": "Midnight Arcade", "uploader": "Casio Tide", "duration": 233.0},
        {"id": 1006, "title": "Afterglow FM", "uploader": "Casio Tide", "duration": 176.0},
    ],
}
for entry in DEMO_SET["entries"]:
    entry["webpage_url"] = f"https://soundcloud.com/demo/{entry['id']}"


class DemoYDL:
    """Copies the CC0 fixture into place while firing paced progress hooks."""

    def __init__(self, opts: dict[str, Any]) -> None:
        self.opts = opts

    def __enter__(self) -> DemoYDL:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def extract_info(self, url: str, download: bool = True) -> dict[str, Any]:
        video_id = url.rstrip("/").rsplit("/", 1)[-1]
        hooks = self.opts.get("progress_hooks") or []
        total = 4_000_000
        for step in range(1, 9):
            for hook in hooks:
                hook(
                    {
                        "status": "downloading",
                        "downloaded_bytes": total * step // 8,
                        "total_bytes": total,
                        "speed": 2.4e6,
                    }
                )
            time.sleep(0.12)
        out = Path(str(self.opts["outtmpl"]).replace("%(id)s", video_id).replace("%(ext)s", "opus"))
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SAMPLE, out)
        for hook in hooks:
            hook({"status": "finished", "filename": str(out)})
        return {"id": video_id, "ext": "opus", "requested_downloads": [{"filepath": str(out)}]}


async def fake_fetch(url: str) -> tuple[bytes, str]:
    return solid_png((94, 129, 172)), "image/png"


async def fake_extract(url: str) -> dict[str, Any]:
    await asyncio.sleep(0.4)  # pretend to resolve
    return DEMO_SET


async def run_once(console: Console, settings: Settings) -> None:
    async with Library(settings.resolved_db_path) as library:
        with ProgressUI(console, total=0) as ui:
            pipeline = Pipeline(
                settings,
                library,
                emit=ui,
                ydl_factory=lambda opts: DemoYDL(opts),
                fetch=fake_fetch,
                resolvers={"soundcloud": SoundCloudResolver(extract=fake_extract)},
            )
            summary = await pipeline.run_url(DEMO_URL)
        render_summary(console, summary)


def main() -> None:
    import sys

    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")  # legacy windows consoles default to cp1252

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export-svg", type=Path, default=None)
    args = parser.parse_args()

    console = Console(record=args.export_svg is not None, width=100, force_terminal=True)
    sandbox = Path(tempfile.mkdtemp(prefix="savesong-demo-"))
    settings = Settings(music_dir=sandbox / "music", db_path=sandbox / "demo.db", concurrency=3)
    try:
        console.print()
        console.print(
            "[bold]$ savesong get[/bold] [cyan]<soundcloud set url>[/cyan]"
            "  [dim](offline demo against fixtures)[/dim]"
        )
        asyncio.run(run_once(console, settings))
        console.print()
        console.print(
            "[bold]$ savesong get[/bold] [cyan]<same url>[/cyan]"
            "  [dim](re-run → library dedupe)[/dim]"
        )
        asyncio.run(run_once(console, settings))
        console.print()
        if args.export_svg:
            args.export_svg.parent.mkdir(parents=True, exist_ok=True)
            console.save_svg(str(args.export_svg), title="savesong")
            print(f"exported {args.export_svg}")
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


if __name__ == "__main__":
    main()
