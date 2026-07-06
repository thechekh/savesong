"""arq worker settings: `uv run arq savesong.worker.WorkerSettings`."""

from __future__ import annotations

from typing import Any, ClassVar

from arq.connections import RedisSettings

from savesong.config import Settings
from savesong.web.jobs import download_job, retry_track


class WorkerSettings:
    functions: ClassVar[list[Any]] = [download_job, retry_track]
    allow_abort_jobs: ClassVar[bool] = True
    max_jobs: ClassVar[int] = 2
    job_timeout: ClassVar[int] = 3600
    keep_result: ClassVar[int] = 3600
    redis_settings: ClassVar[RedisSettings] = RedisSettings.from_dsn(Settings().redis_url)
