"""Config layering: toml < env < init kwarg (flag)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from savesong.config import Settings, config_path, default_config_toml, write_default_config


def test_defaults() -> None:
    s = Settings()
    assert s.format == "opus"
    assert s.concurrency == 4
    assert s.match_threshold == 0.72
    assert s.spotify_client_id is None
    assert s.web_port == 8080
    assert s.music_dir.name == "SaveSong"


def test_resolved_db_path_defaults_under_music_dir(tmp_path: Path) -> None:
    s = Settings(music_dir=tmp_path / "m")
    assert s.resolved_db_path == tmp_path / "m" / ".savesong" / "savesong.db"
    explicit = Settings(music_dir=tmp_path / "m", db_path=tmp_path / "x.db")
    assert explicit.resolved_db_path == tmp_path / "x.db"


def test_toml_layer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        'music_dir = "C:/toml-music"\nformat = "mp3"\nconcurrency = 9\n'
        'spotify_client_id = "from-toml"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SAVESONG_CONFIG", str(cfg))
    s = Settings()
    assert s.music_dir == Path("C:/toml-music")
    assert s.format == "mp3"
    assert s.concurrency == 9
    assert s.spotify_client_id == "from-toml"


def test_env_beats_toml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('format = "mp3"\nconcurrency = 9\n', encoding="utf-8")
    monkeypatch.setenv("SAVESONG_CONFIG", str(cfg))
    monkeypatch.setenv("SAVESONG_FORMAT", "m4a")
    s = Settings()
    assert s.format == "m4a"
    assert s.concurrency == 9  # untouched by env, still from toml


def test_flag_beats_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAVESONG_FORMAT", "m4a")
    monkeypatch.setenv("SAVESONG_CONCURRENCY", "2")
    s = Settings(format="mp3")
    assert s.format == "mp3"
    assert s.concurrency == 2


def test_unprefixed_env_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id-from-env")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "secret-from-env")
    monkeypatch.setenv("REDIS_URL", "redis://elsewhere:6379/2")
    s = Settings()
    assert s.spotify_client_id == "id-from-env"
    assert s.spotify_client_secret == "secret-from-env"
    assert s.redis_url == "redis://elsewhere:6379/2"


def test_music_dir_expands_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAVESONG_MUSIC_DIR", "~/tunes")
    s = Settings()
    assert "~" not in str(s.music_dir)
    assert s.music_dir.name == "tunes"


def test_config_path_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SAVESONG_CONFIG", str(tmp_path / "custom.toml"))
    assert config_path() == tmp_path / "custom.toml"


def test_default_config_toml_parses() -> None:
    data = tomllib.loads(default_config_toml())
    assert data["format"] == "opus"
    assert data["concurrency"] == 4
    assert "spotify_client_id" in data


def test_write_default_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "cfg" / "config.toml"
    monkeypatch.setenv("SAVESONG_CONFIG", str(target))
    written = write_default_config()
    assert written == target
    assert target.exists()
    with pytest.raises(FileExistsError):
        write_default_config()
    write_default_config(force=True)  # no raise
