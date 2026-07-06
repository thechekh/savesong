"""Layered configuration: CLI flag > environment > config.toml > default.

Environment variables use the ``SAVESONG_`` prefix except the conventional
``SPOTIFY_CLIENT_ID`` / ``SPOTIFY_CLIENT_SECRET`` / ``REDIS_URL``.
The TOML file lives at ``~/.config/savesong/config.toml`` (override with
``SAVESONG_CONFIG``); ``savesong config init`` scaffolds it.
"""

from __future__ import annotations

import os
from pathlib import Path

import tomli_w
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from savesong.models import AudioFormat

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "savesong" / "config.toml"

_CONFIG_HEADER = """\
# SaveSong configuration.
# Every key can be overridden by an environment variable (SAVESONG_MUSIC_DIR, ...)
# or a CLI flag; precedence: flag > env > this file > default.
# Optional keys: db_path (defaults to <music_dir>/.savesong/savesong.db),
# redis_url (web mode only), web_port.
"""


def config_path() -> Path:
    """Path of the active config file (honours the SAVESONG_CONFIG override)."""
    return Path(os.environ.get("SAVESONG_CONFIG", str(DEFAULT_CONFIG_PATH))).expanduser()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SAVESONG_",
        extra="ignore",
        populate_by_name=True,
    )

    music_dir: Path = Path.home() / "Music" / "SaveSong"
    db_path: Path | None = None
    format: AudioFormat = "opus"
    concurrency: int = Field(default=4, ge=1, le=16)
    match_threshold: float = Field(default=0.72, ge=0.0, le=1.0)
    spotify_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SPOTIFY_CLIENT_ID", "spotify_client_id"),
    )
    spotify_client_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SPOTIFY_CLIENT_SECRET", "spotify_client_secret"),
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("REDIS_URL", "redis_url"),
    )
    web_port: int = Field(default=8080, ge=1, le=65535)

    @field_validator("music_dir", "db_path", mode="after")
    @classmethod
    def _expand_user(cls, value: Path | None) -> Path | None:
        return value.expanduser() if value is not None else None

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        toml_settings = TomlConfigSettingsSource(settings_cls, toml_file=config_path())
        return (init_settings, env_settings, dotenv_settings, toml_settings, file_secret_settings)

    @property
    def resolved_db_path(self) -> Path:
        if self.db_path is not None:
            return self.db_path
        return self.music_dir / ".savesong" / "savesong.db"


def default_config_toml(settings: Settings | None = None) -> str:
    """Render the scaffold config file content."""
    s = settings or Settings()
    body = tomli_w.dumps(
        {
            "music_dir": s.music_dir.as_posix(),
            "format": s.format,
            "concurrency": s.concurrency,
            "match_threshold": s.match_threshold,
            "spotify_client_id": s.spotify_client_id or "",
            "spotify_client_secret": s.spotify_client_secret or "",
        }
    )
    return _CONFIG_HEADER + body


def write_default_config(path: Path | None = None, *, force: bool = False) -> Path:
    """Scaffold the config file; refuses to overwrite unless ``force``."""
    dest = path or config_path()
    if dest.exists() and not force:
        raise FileExistsError(f"config already exists: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(default_config_toml(), encoding="utf-8")
    return dest
