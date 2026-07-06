"""Async SQLAlchemy engine/session factories for the SQLite library."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def sqlite_url(db_path: Path, *, driver: str = "aiosqlite") -> str:
    prefix = f"sqlite+{driver}" if driver else "sqlite"
    return f"{prefix}:///{db_path.expanduser().as_posix()}"


def create_db_engine(db_path: Path) -> AsyncEngine:
    db_path = db_path.expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return create_async_engine(sqlite_url(db_path))


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
