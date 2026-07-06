"""FastAPI application factory.

`uvicorn savesong.web.app:create_app --factory`; tests inject a fake Redis
pool and a temp-directory Library.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

import savesong
from savesong.config import Settings
from savesong.core.library import Library
from savesong.web.routes import router


def create_app(
    settings: Settings | None = None,
    *,
    redis: Any | None = None,
    library: Library | None = None,
) -> FastAPI:
    app_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        lib = library
        owns_library = lib is None
        if lib is None:
            lib = await Library(app_settings.resolved_db_path).open()
        redis_pool = redis
        owns_redis = redis_pool is None
        if redis_pool is None:  # pragma: no cover - needs a real redis
            from arq.connections import RedisSettings, create_pool

            redis_pool = await create_pool(RedisSettings.from_dsn(app_settings.redis_url))
        app.state.settings = app_settings
        app.state.library = lib
        app.state.redis = redis_pool
        try:
            yield
        finally:
            if owns_redis:  # pragma: no cover - needs a real redis
                await redis_pool.aclose()
            if owns_library:
                await lib.close()

    app = FastAPI(title="SaveSong", version=savesong.__version__, lifespan=lifespan)
    app.include_router(router)
    return app
