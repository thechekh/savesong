"""Initial schema: playlists, tracks, jobs.

Revision ID: 0001
Revises:
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "playlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("last_synced_at", sa.Text(), nullable=True),
        sa.UniqueConstraint("source", "external_id", name="uq_playlists_source_external_id"),
        sa.CheckConstraint(
            "source IN ('spotify','soundcloud','ytmusic')", name="ck_playlists_source"
        ),
    )

    op.create_table(
        "tracks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("playlist_id", sa.Integer(), sa.ForeignKey("playlists.id"), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("artists", sa.Text(), nullable=False),
        sa.Column("album", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("cover_url", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("matched_video_id", sa.Text(), nullable=True),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("match_candidates", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("downloaded_at", sa.Text(), nullable=True),
        sa.UniqueConstraint(
            "source", "external_id", "playlist_id", name="uq_tracks_source_external_playlist"
        ),
        sa.CheckConstraint(
            "status IN ('pending','matched','downloading','done',"
            "'failed','needs_review','skipped')",
            name="ck_tracks_status",
        ),
    )
    op.create_index("tracks_status", "tracks", ["status"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("total", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("completed", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("failed", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "state IN ('queued','resolving','running','done','failed','cancelled')",
            name="ck_jobs_state",
        ),
    )


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_index("tracks_status", table_name="tracks")
    op.drop_table("tracks")
    op.drop_table("playlists")
