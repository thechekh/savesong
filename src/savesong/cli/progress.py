"""Rich rendering of pipeline JobProgress events: overall bar + per-track bars."""

from __future__ import annotations

from types import TracebackType

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from savesong.models import DownloadResult, JobProgress, Summary

MAX_VISIBLE_TRACKS = 8

_STATUS_STYLE = {
    "done": "green",
    "skipped": "dim",
    "failed": "red",
    "needs_review": "yellow",
}


class ProgressUI:
    """Consumes :class:`JobProgress` events; renders an overall bar plus
    per-track bars (at most :data:`MAX_VISIBLE_TRACKS` visible at once)."""

    def __init__(self, console: Console, total: int) -> None:
        self.console = console
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}", justify="left"),
            BarColumn(bar_width=30),
            TaskProgressColumn(),
            TextColumn("{task.fields[speed]}", style="cyan"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        )
        self._overall: TaskID = self._progress.add_task(
            "[bold]overall", total=max(total, 1), speed=""
        )
        self._tracks: dict[str, TaskID] = {}

    def __enter__(self) -> ProgressUI:
        self._progress.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._progress.stop()

    def __call__(self, event: JobProgress) -> None:
        if event.event == "progress":
            self._on_progress(event)
        elif event.event == "track_done":
            self._on_track_done(event)

    def _task_for(self, event: JobProgress) -> TaskID:
        key = event.external_id or str(event.track_id)
        if key not in self._tracks:
            title = (event.title or key)[:40]
            visible = len(self._tracks) < MAX_VISIBLE_TRACKS
            self._tracks[key] = self._progress.add_task(
                title, total=100.0, speed="", visible=visible
            )
        return self._tracks[key]

    def _on_progress(self, event: JobProgress) -> None:
        task = self._task_for(event)
        self._progress.update(task, completed=event.pct or 0.0, speed=event.speed or "")

    def _on_track_done(self, event: JobProgress) -> None:
        key = event.external_id or str(event.track_id)
        task = self._tracks.pop(key, None)
        if task is not None:
            self._progress.remove_task(task)
        self._progress.advance(self._overall, 1)
        style = _STATUS_STYLE.get(event.status or "", "white")
        label = (event.status or "?").replace("_", " ")
        detail = f" [red]({event.error})[/red]" if event.error else ""
        self.console.print(
            f"  [{style}]{label:>12}[/{style}]  {event.title or event.external_id}{detail}",
            highlight=False,
        )


def render_summary(console: Console, summary: Summary) -> None:
    table = Table(title="SaveSong summary", show_edge=False, pad_edge=False)
    table.add_column("outcome", style="bold")
    table.add_column("count", justify="right")
    table.add_row("[green]downloaded", str(summary.downloaded))
    table.add_row("[dim]skipped (already in library)", str(summary.skipped))
    table.add_row("[red]failed", str(summary.failed))
    table.add_row("[yellow]needs review", str(summary.needs_review))
    console.print(table)
    if summary.m3u_path:
        console.print(f"playlist written: [bold]{summary.m3u_path}[/bold]")
    failed = [r for r in summary.results if r.status == "failed"]
    if failed:
        console.print("\n[red bold]failed tracks[/red bold] (retry with `savesong retry-failed`):")
        for r in failed:
            console.print(f"  [red]✗[/red] {r.track.artist_display} - {r.track.title}: {r.error}")
    review = [r for r in summary.results if r.status == "needs_review"]
    if review:
        console.print(
            "\n[yellow bold]needs review[/yellow bold] (pick manually with `savesong review`):"
        )
        for r in review:
            score = f" (best score {r.match.score:.2f})" if r.match else ""
            console.print(f"  [yellow]?[/yellow] {r.track.artist_display} - {r.track.title}{score}")


def render_matches(console: Console, results: list[DownloadResult], threshold: float) -> None:
    """--dry-run output: the match table with scores."""
    table = Table(title=f"match plan (threshold {threshold:.2f})")
    table.add_column("track")
    table.add_column("best candidate")
    table.add_column("score", justify="right")
    table.add_column("verdict")
    for r in results:
        name = f"{r.track.artist_display} - {r.track.title}"
        if r.status == "skipped":
            table.add_row(name, "[dim]already in library[/dim]", "-", "[dim]skip[/dim]")
            continue
        if r.match is None or r.match.best is None:
            if r.status == "matched":
                table.add_row(
                    name,
                    "[dim]direct download (no matching needed)[/dim]",
                    "-",
                    "[green]ok[/green]",
                )
            else:
                table.add_row(
                    name, "[yellow]no candidates[/yellow]", "0.00", "[yellow]review[/yellow]"
                )
            continue
        verdict = (
            "[yellow]review[/yellow]" if r.status == "needs_review" else "[green]download[/green]"
        )
        table.add_row(
            name,
            f"{r.match.best.title} [dim]({r.match.best.channel})[/dim]",
            f"{r.match.score:.2f}",
            verdict,
        )
    console.print(table)
