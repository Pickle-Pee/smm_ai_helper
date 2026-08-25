"""add durable job persistence

Revision ID: 20260825_0004
Revises: 20260814_0003
Create Date: 2026-08-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260825_0004"
down_revision = "20260814_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("marketing_run_id", sa.String(length=64), nullable=True),
        sa.Column("workflow_step", sa.String(length=64), nullable=True),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "result_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error", sa.String(length=4000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "job_id ~ '^[0-9a-f]{32}$'",
            name="ck_jobs_job_id_format",
        ),
        sa.CheckConstraint(
            "kind ~ '^[a-z][a-z0-9_.-]{0,63}$'",
            name="ck_jobs_kind_format",
        ),
        sa.CheckConstraint(
            "workflow_step IS NULL "
            "OR workflow_step ~ '^[a-z][a-z0-9_.-]{0,63}$'",
            name="ck_jobs_workflow_step_format",
        ),
        sa.CheckConstraint(
            "marketing_run_id IS NULL OR user_id IS NULL",
            name="ck_jobs_exclusive_owner",
        ),
        sa.CheckConstraint(
            "workflow_step IS NULL OR marketing_run_id IS NOT NULL",
            name="ck_jobs_step_requires_run",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_jobs_status",
        ),
        sa.CheckConstraint(
            "version >= 0",
            name="ck_jobs_version_nonnegative",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload_json) = 'object'",
            name="ck_jobs_payload_object",
        ),
        sa.CheckConstraint(
            "result_json IS NULL OR jsonb_typeof(result_json) = 'object'",
            name="ck_jobs_result_object",
        ),
        sa.CheckConstraint(
            r"""
            (
                status = 'pending'
                AND started_at IS NULL
                AND completed_at IS NULL
                AND result_json IS NULL
                AND error IS NULL
            )
            OR (
                status = 'running'
                AND started_at IS NOT NULL
                AND completed_at IS NULL
                AND result_json IS NULL
                AND error IS NULL
            )
            OR (
                status = 'succeeded'
                AND started_at IS NOT NULL
                AND completed_at IS NOT NULL
                AND result_json IS NOT NULL
                AND error IS NULL
            )
            OR (
                status = 'failed'
                AND started_at IS NOT NULL
                AND completed_at IS NOT NULL
                AND result_json IS NULL
                AND error IS NOT NULL
                AND btrim(error, E'\x09\x0A\x0B\x0C\x0D\x20') <> ''
            )
            """,
            name="ck_jobs_lifecycle",
        ),
        sa.CheckConstraint(
            """
            updated_at >= created_at
            AND (started_at IS NULL OR started_at >= created_at)
            AND (
                completed_at IS NULL
                OR (
                    started_at IS NOT NULL
                    AND completed_at >= started_at
                )
            )
            AND (
                (status = 'pending' AND updated_at = created_at)
                OR (status = 'running' AND updated_at = started_at)
                OR (
                    status IN ('succeeded', 'failed')
                    AND updated_at = completed_at
                )
            )
            """,
            name="ck_jobs_timestamp_order",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["marketing_run_id"],
            ["marketing_runs.run_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index(
        "ix_jobs_run_created_job",
        "jobs",
        ["marketing_run_id", "created_at", "job_id"],
        unique=False,
    )
    op.create_index(
        "ix_jobs_status_created_job",
        "jobs",
        ["status", "created_at", "job_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_status_created_job", table_name="jobs")
    op.drop_index("ix_jobs_run_created_job", table_name="jobs")
    op.drop_table("jobs")
