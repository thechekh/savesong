# API / worker / migrate image: python 3.12 + ffmpeg 7 (Debian trixie), uv-built venv.
FROM python:3.12-slim-trixie AS builder
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-trixie
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    SAVESONG_MUSIC_DIR=/music \
    SAVESONG_DB_PATH=/data/savesong.db
RUN mkdir -p /music /data
EXPOSE 8000
CMD ["uvicorn", "savesong.web.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
