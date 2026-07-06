"""CLI end-to-end (offline): typer CliRunner with a stubbed pipeline seam."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

import savesong.cli.main as cli_main
from savesong.core.pipeline import Pipeline
from savesong.core.resolvers.soundcloud import SoundCloudResolver
from tests.conftest import make_fake_ydl_factory
from tests.integration.test_resolvers_ytdlp import SC_SET

SC_URL = "https://soundcloud.com/dj-orbit/sets/late-night-mix"

runner = CliRunner()


@pytest.fixture
def cli_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, sample_opus: Path, fake_fetch: Any
) -> Path:
    music = tmp_path / "music"
    monkeypatch.setenv("SAVESONG_MUSIC_DIR", str(music))
    monkeypatch.setenv("SAVESONG_DB_PATH", str(tmp_path / "cli.db"))

    async def extract(url: str) -> dict[str, Any]:
        return SC_SET

    def factory(settings: Any, library: Any, emit: Any = None, **kwargs: Any) -> Pipeline:
        return Pipeline(
            settings,
            library,
            emit=emit,
            ydl_factory=make_fake_ydl_factory(sample_opus),
            fetch=fake_fetch,
            resolvers={"soundcloud": SoundCloudResolver(extract=extract)},
        )

    monkeypatch.setattr(cli_main, "_pipeline_factory", factory)
    return music


def test_help_lists_commands() -> None:
    result = runner.invoke(cli_main.app, ["--help"])
    assert result.exit_code == 0
    for command in ("get", "sync", "library", "export-m3u", "retry-failed", "review", "config"):
        assert command in result.output


def test_version_flag() -> None:
    result = runner.invoke(cli_main.app, ["--version"])
    assert result.exit_code == 0
    assert "savesong" in result.output


def test_get_downloads_playlist(cli_env: Path) -> None:
    result = runner.invoke(cli_main.app, ["get", SC_URL])
    assert result.exit_code == 0, result.output
    files = sorted(p.name for p in cli_env.rglob("*.opus"))
    assert files == ["01 - First Wave.opus", "02 - Second Wave.opus"]
    assert (cli_env / "Late Night Mix.m3u8").exists()
    assert "downloaded" in result.output


def test_get_rerun_skips(cli_env: Path) -> None:
    assert runner.invoke(cli_main.app, ["get", SC_URL]).exit_code == 0
    result = runner.invoke(cli_main.app, ["get", SC_URL])
    assert result.exit_code == 0
    assert "skipped" in result.output
    # still exactly two files — no duplicates
    assert len(list(cli_env.rglob("*.opus"))) == 2


def test_get_dry_run_downloads_nothing(cli_env: Path) -> None:
    result = runner.invoke(cli_main.app, ["get", SC_URL, "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "match plan" in result.output
    assert not list(cli_env.rglob("*.opus"))


def test_get_unsupported_url_exits_2(cli_env: Path) -> None:
    result = runner.invoke(cli_main.app, ["get", "https://example.com/whatever"])
    assert result.exit_code == 2
    assert "error" in result.output


def test_get_rejects_bad_format(cli_env: Path) -> None:
    result = runner.invoke(cli_main.app, ["get", SC_URL, "--format", "flac"])
    assert result.exit_code != 0


def test_library_list_and_stats(cli_env: Path) -> None:
    empty = runner.invoke(cli_main.app, ["library", "list"])
    assert empty.exit_code == 0 and "empty" in empty.output

    runner.invoke(cli_main.app, ["get", SC_URL])
    listing = runner.invoke(cli_main.app, ["library", "list"])
    assert listing.exit_code == 0
    assert "First Wave" in listing.output

    filtered = runner.invoke(cli_main.app, ["library", "list", "--q", "Second"])
    assert "Second Wave" in filtered.output and "First Wave" not in filtered.output

    stats = runner.invoke(cli_main.app, ["library", "stats"])
    assert stats.exit_code == 0
    assert "playlists" in stats.output and "Late Night Mix" in stats.output


def test_export_m3u(cli_env: Path, tmp_path: Path) -> None:
    runner.invoke(cli_main.app, ["get", SC_URL])
    out = tmp_path / "exported.m3u8"
    result = runner.invoke(cli_main.app, ["export-m3u", "1", "--out", str(out), "--relative"])
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "#EXTM3U" in out.read_text(encoding="utf-8")

    missing = runner.invoke(cli_main.app, ["export-m3u", "999"])
    assert missing.exit_code == 2


def test_sync_command(cli_env: Path) -> None:
    result = runner.invoke(cli_main.app, ["sync", SC_URL])
    assert result.exit_code == 0, result.output
    assert len(list(cli_env.rglob("*.opus"))) == 2


def test_retry_failed_with_nothing(cli_env: Path) -> None:
    result = runner.invoke(cli_main.app, ["retry-failed"])
    assert result.exit_code == 0
    assert "nothing to retry" in result.output


def test_config_init(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "cfg" / "config.toml"
    monkeypatch.setenv("SAVESONG_CONFIG", str(target))
    first = runner.invoke(cli_main.app, ["config", "init"])
    assert first.exit_code == 0 and target.exists()
    again = runner.invoke(cli_main.app, ["config", "init"])
    assert again.exit_code == 1
    forced = runner.invoke(cli_main.app, ["config", "init", "--force"])
    assert forced.exit_code == 0
