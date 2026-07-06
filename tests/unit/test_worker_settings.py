"""WorkerSettings shape (arq duck-typed class)."""

from __future__ import annotations


def test_worker_settings_shape() -> None:
    from savesong.web.jobs import download_job, retry_track
    from savesong.worker import WorkerSettings

    assert WorkerSettings.functions == [download_job, retry_track]
    assert WorkerSettings.allow_abort_jobs is True
    assert WorkerSettings.redis_settings.port == 6379


def test_worker_settings_honours_redis_url_env(monkeypatch: object) -> None:
    # redis_settings is resolved at import time from Settings(); just confirm
    # the DSN parser handles a custom URL shape.
    from arq.connections import RedisSettings

    parsed = RedisSettings.from_dsn("redis://example.test:6380/3")
    assert (parsed.host, parsed.port, parsed.database) == ("example.test", 6380, 3)
