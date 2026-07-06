"""Programmatic Alembic upgrades — CLI and web both migrate on startup.

Also runnable directly (``python -m savesong.db.migrate``) for the docker
compose one-shot migrate service.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from alembic import command
from alembic.config import Config

from savesong.db.engine import sqlite_url


def alembic_config(db_path: Path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(files("savesong.db").joinpath("alembic")))
    cfg.set_main_option("sqlalchemy.url", sqlite_url(db_path, driver=""))
    return cfg


def upgrade_to_head(db_path: Path) -> None:
    db_path = db_path.expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(alembic_config(db_path), "head")


def main() -> None:
    from savesong.config import Settings

    db_path = Settings().resolved_db_path
    upgrade_to_head(db_path)
    print(f"database migrated: {db_path}")


if __name__ == "__main__":
    main()
