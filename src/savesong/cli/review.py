"""`savesong review` — interactive pick among stored top-3 candidates."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from savesong.cli.progress import ProgressUI, render_summary
from savesong.config import Settings
from savesong.core.library import Library
from savesong.core.pipeline import Pipeline
from savesong.db.tables import TrackRow

AskFn = Callable[[str, list[str]], str]
ConfirmFn = Callable[[str], bool]

_pipeline_factory = Pipeline


def _default_ask(prompt: str, choices: list[str]) -> str:
    return Prompt.ask(prompt, choices=choices)


def _default_confirm(prompt: str) -> bool:
    return Confirm.ask(prompt, default=True)


def run_review(
    settings: Settings,
    console: Console,
    *,
    ask: AskFn | None = None,
    confirm: ConfirmFn | None = None,
) -> int:
    return asyncio.run(_review(settings, console, ask or _default_ask, confirm or _default_confirm))


def _fmt_duration(seconds: Any) -> str:
    if not seconds:
        return "-"
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


async def _review(settings: Settings, console: Console, ask: AskFn, confirm: ConfirmFn) -> int:
    async with Library(settings.resolved_db_path) as library:
        rows = await library.needs_review_tracks()
        if not rows:
            console.print("nothing needs review")
            return 0

        picked: list[TrackRow] = []
        for row in rows:
            try:
                candidates = json.loads(row.match_candidates or "[]")
            except ValueError:
                candidates = []
            if not candidates:
                console.print(f"[dim]{row.title}: no stored candidates — skipping[/dim]")
                continue

            table = Table(title=f"{', '.join(row.artists_list)} — {row.title}")
            table.add_column("#", justify="right")
            table.add_column("candidate title")
            table.add_column("channel")
            table.add_column("length", justify="right")
            table.add_column("score", justify="right")
            for i, cand in enumerate(candidates, 1):
                table.add_row(
                    str(i),
                    str(cand.get("title", "")),
                    str(cand.get("channel", "")),
                    _fmt_duration(cand.get("duration_s")),
                    f"{float(cand.get('score') or 0):.2f}",
                )
            console.print(table)

            choices = [str(i) for i in range(1, len(candidates) + 1)] + ["s", "q"]
            answer = ask("pick a candidate, [s]kip, or [q]uit", choices)
            if answer == "q":
                break
            if answer == "s":
                continue
            chosen = candidates[int(answer) - 1]
            await library.mark_matched(
                row.id,
                str(chosen["video_id"]),
                float(chosen.get("score") or 0.0),
                json.dumps(candidates),
            )
            refreshed = await library.get_track(row.id)
            if refreshed is not None:
                picked.append(refreshed)
            console.print(f"[green]matched[/green] {row.title} → {chosen.get('title')}")

        if not picked:
            return 0
        if not confirm(f"download {len(picked)} picked track(s) now?"):
            console.print("picks saved — they will download on the next run")
            return 0

        with ProgressUI(console, total=len(picked)) as ui:
            pipeline = _pipeline_factory(settings, library, emit=ui)
            try:
                summary = await pipeline.download_rows(picked)
            finally:
                await pipeline.aclose()
        render_summary(console, summary)
        return 1 if summary.failed > 0 and summary.downloaded == 0 else 0
