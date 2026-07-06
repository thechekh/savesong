"""SaveSong CLI — Typer commands, Rich rendering; zero business logic."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

import savesong
from savesong.cli.progress import ProgressUI, render_matches, render_summary
from savesong.config import Settings, config_path, write_default_config
from savesong.core.library import Library
from savesong.core.m3u import write_m3u8
from savesong.core.pipeline import Pipeline, row_to_meta
from savesong.errors import SaveSongError
from savesong.models import AUDIO_FORMATS, Summary

app = typer.Typer(
    name="savesong",
    help="Download playlists/tracks from Spotify, SoundCloud, and YouTube Music — "
    "tagged, organized, and deduped into a local library.",
    no_args_is_help=True,
    add_completion=False,
)
library_app = typer.Typer(help="Inspect the local library.", no_args_is_help=True)
config_app = typer.Typer(help="Manage configuration.", no_args_is_help=True)
app.add_typer(library_app, name="library")
app.add_typer(config_app, name="config")

console = Console()

# module-level seam so tests can substitute an offline pipeline
_pipeline_factory = Pipeline

FormatOption = Annotated[
    str | None,
    typer.Option("--format", "-f", help=f"Audio format: {'|'.join(AUDIO_FORMATS)}."),
]
ConcurrencyOption = Annotated[
    int | None, typer.Option("--concurrency", "-c", min=1, max=16, help="Parallel downloads.")
]
MusicDirOption = Annotated[
    Path | None, typer.Option("--music-dir", help="Root of the music library.")
]


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"savesong {savesong.__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version_callback, is_eager=True)
    ] = False,
) -> None:
    """SaveSong — for personal archiving of content you have rights to access."""


def _make_settings(
    music_dir: Path | None = None,
    fmt: str | None = None,
    concurrency: int | None = None,
) -> Settings:
    overrides: dict[str, Any] = {}
    if music_dir is not None:
        overrides["music_dir"] = music_dir
    if fmt is not None:
        if fmt not in AUDIO_FORMATS:
            raise typer.BadParameter(f"format must be one of: {', '.join(AUDIO_FORMATS)}")
        overrides["format"] = fmt
    if concurrency is not None:
        overrides["concurrency"] = concurrency
    return Settings(**overrides)


def _fail(exc: BaseException) -> None:
    console.print(f"[red bold]error:[/red bold] {exc}")
    raise typer.Exit(2)


def _exit_code(summary: Summary) -> int:
    if summary.failed > 0 and summary.downloaded == 0 and summary.skipped == 0:
        return 1
    return 0


@app.command()
def get(
    url: Annotated[str, typer.Argument(help="Playlist or track URL (source auto-detected).")],
    format: FormatOption = None,
    concurrency: ConcurrencyOption = None,
    music_dir: MusicDirOption = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Resolve + match only; download nothing.")
    ] = False,
) -> None:
    """Download a playlist or single track."""
    settings = _make_settings(music_dir, format, concurrency)
    try:
        code = asyncio.run(_get_async(settings, url, dry_run))
    except KeyboardInterrupt:
        console.print("\n[yellow]cancelled — partial files cleaned up[/yellow]")
        raise typer.Exit(130) from None
    except SaveSongError as exc:
        _fail(exc)
        return
    raise typer.Exit(code)


async def _get_async(settings: Settings, url: str, dry_run: bool) -> int:
    async with Library(settings.resolved_db_path) as library:
        if dry_run:
            pipeline = _pipeline_factory(settings, library)
            try:
                with console.status("resolving and matching…"):
                    results = await pipeline.dry_run(url)
            finally:
                await pipeline.aclose()
            render_matches(console, results, settings.match_threshold)
            return 0
        with ProgressUI(console, total=0) as ui:
            pipeline = _pipeline_factory(settings, library, emit=ui)
            try:
                summary = await pipeline.run_url(url)
            finally:
                await pipeline.aclose()
        render_summary(console, summary)
        return _exit_code(summary)


@app.command()
def sync(
    url: Annotated[str, typer.Argument(help="Playlist URL previously downloaded.")],
    format: FormatOption = None,
    concurrency: ConcurrencyOption = None,
    music_dir: MusicDirOption = None,
    prune: Annotated[
        bool, typer.Option("--prune", help="Delete local files for tracks removed upstream.")
    ] = False,
) -> None:
    """Diff a playlist against the library: download additions, flag removals."""
    settings = _make_settings(music_dir, format, concurrency)
    try:
        code = asyncio.run(_sync_async(settings, url, prune))
    except KeyboardInterrupt:
        console.print("\n[yellow]cancelled — partial files cleaned up[/yellow]")
        raise typer.Exit(130) from None
    except SaveSongError as exc:
        _fail(exc)
        return
    raise typer.Exit(code)


async def _sync_async(settings: Settings, url: str, prune: bool) -> int:
    async with Library(settings.resolved_db_path) as library:
        with ProgressUI(console, total=0) as ui:
            pipeline = _pipeline_factory(settings, library, emit=ui)
            try:
                summary, removed = await pipeline.sync_url(url, prune=prune)
            finally:
                await pipeline.aclose()
        render_summary(console, summary)
        if removed:
            action = "pruned" if prune else "no longer in the source playlist (use --prune)"
            console.print(f"\n[yellow]{len(removed)} track(s) {action}:[/yellow]")
            for row in removed:
                console.print(f"  - {', '.join(row.artists_list)} - {row.title}")
        return _exit_code(summary)


@app.command("retry-failed")
def retry_failed(
    format: FormatOption = None,
    concurrency: ConcurrencyOption = None,
    music_dir: MusicDirOption = None,
) -> None:
    """Retry every track currently marked as failed."""
    settings = _make_settings(music_dir, format, concurrency)
    try:
        code = asyncio.run(_retry_async(settings))
    except KeyboardInterrupt:
        console.print("\n[yellow]cancelled — partial files cleaned up[/yellow]")
        raise typer.Exit(130) from None
    except SaveSongError as exc:
        _fail(exc)
        return
    raise typer.Exit(code)


async def _retry_async(settings: Settings) -> int:
    async with Library(settings.resolved_db_path) as library:
        failed = await library.failed_tracks()
        if not failed:
            console.print("no failed tracks — nothing to retry")
            return 0
        with ProgressUI(console, total=len(failed)) as ui:
            pipeline = _pipeline_factory(settings, library, emit=ui)
            try:
                summary = await pipeline.retry_failed()
            finally:
                await pipeline.aclose()
        render_summary(console, summary)
        return _exit_code(summary)


@app.command()
def review(music_dir: MusicDirOption = None) -> None:
    """Interactively pick among stored candidates for needs_review tracks."""
    from savesong.cli.review import run_review

    settings = _make_settings(music_dir)
    raise typer.Exit(run_review(settings, console))


@app.command("export-m3u")
def export_m3u(
    playlist_id: Annotated[
        int, typer.Argument(help="Library playlist id (see `savesong library stats`).")
    ],
    relative: Annotated[
        bool, typer.Option("--relative", help="Write paths relative to the playlist file.")
    ] = False,
    out: Annotated[Path | None, typer.Option("--out", help="Output path.")] = None,
    music_dir: MusicDirOption = None,
) -> None:
    """Export a playlist's downloaded tracks as .m3u8."""
    settings = _make_settings(music_dir)
    try:
        path = asyncio.run(_export_async(settings, playlist_id, relative, out))
    except SaveSongError as exc:
        _fail(exc)
        return
    console.print(f"wrote [bold]{path}[/bold]")


async def _export_async(
    settings: Settings, playlist_id: int, relative: bool, out: Path | None
) -> Path:
    async with Library(settings.resolved_db_path) as library:
        playlist = await library.get_playlist(playlist_id)
        if playlist is None:
            raise SaveSongError(f"no playlist with id {playlist_id} in the library")
        rows = await library.done_tracks_for_playlist(playlist_id)
        if not rows:
            raise SaveSongError(f"playlist {playlist.title!r} has no downloaded tracks yet")
        from savesong.core.organizer import sanitize_component

        dest = out or settings.music_dir / f"{sanitize_component(playlist.title)}.m3u8"
        entries = [(Path(str(r.file_path)), row_to_meta(r)) for r in rows if r.file_path]
        return write_m3u8(dest, entries, relative=relative)


@library_app.command("list")
def library_list(
    q: Annotated[str | None, typer.Option("--q", help="Filter by title/artist/album.")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 50,
    music_dir: MusicDirOption = None,
) -> None:
    """List downloaded tracks."""
    settings = _make_settings(music_dir)
    rows, _cursor = asyncio.run(_library_list_async(settings, q, limit))
    if not rows:
        console.print("library is empty — try `savesong get <url>`")
        return
    table = Table(title="library")
    table.add_column("id", justify="right")
    table.add_column("artist")
    table.add_column("title")
    table.add_column("album")
    table.add_column("downloaded")
    for row in rows:
        table.add_row(
            str(row.id),
            ", ".join(row.artists_list),
            row.title,
            row.album or "-",
            (row.downloaded_at or "-")[:10],
        )
    console.print(table)


async def _library_list_async(
    settings: Settings, q: str | None, limit: int
) -> tuple[list[Any], int | None]:
    async with Library(settings.resolved_db_path) as library:
        return await library.list_library(q=q, limit=limit)


@library_app.command("stats")
def library_stats(music_dir: MusicDirOption = None) -> None:
    """Counts by status, plus playlists with their ids."""
    settings = _make_settings(music_dir)
    stats, playlists = asyncio.run(_library_stats_async(settings))
    table = Table(title="library stats")
    table.add_column("metric")
    table.add_column("count", justify="right")
    for key in ("playlists", "tracks", "done", "failed", "needs_review", "pending", "skipped"):
        if key in stats:
            table.add_row(key, str(stats[key]))
    console.print(table)
    if playlists:
        ptable = Table(title="playlists")
        ptable.add_column("id", justify="right")
        ptable.add_column("source")
        ptable.add_column("title")
        ptable.add_column("last synced")
        for p in playlists:
            ptable.add_row(str(p.id), p.source, p.title, (p.last_synced_at or "never")[:19])
        console.print(ptable)


async def _library_stats_async(settings: Settings) -> tuple[dict[str, int], list[Any]]:
    async with Library(settings.resolved_db_path) as library:
        return await library.stats(), await library.list_playlists()


@config_app.command("init")
def config_init(
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
) -> None:
    """Scaffold ~/.config/savesong/config.toml."""
    try:
        path = write_default_config(force=force)
    except FileExistsError:
        console.print(
            f"[yellow]config already exists:[/yellow] {config_path()} (use --force to overwrite)"
        )
        raise typer.Exit(1) from None
    console.print(f"wrote [bold]{path}[/bold]")
    console.print("add SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET there to enable Spotify playlists")


if __name__ == "__main__":  # pragma: no cover
    app()
