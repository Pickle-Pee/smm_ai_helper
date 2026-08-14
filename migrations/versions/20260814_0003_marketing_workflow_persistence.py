"""add marketing workflow persistence

Revision ID: 20260814_0003
Revises: 20260711_0002
Create Date: 2026-08-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260814_0003"
down_revision = "20260711_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "marketing_runs",
        sa.Column("run_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("workflow_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("current_step", sa.String(length=64), nullable=True),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("state_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_marketing_runs_user_id", "marketing_runs", ["user_id"])
    op.create_index(
        "ix_marketing_runs_workflow_type",
        "marketing_runs",
        ["workflow_type"],
    )
    op.create_index("ix_marketing_runs_status", "marketing_runs", ["status"])

    op.create_table(
        "marketing_artifacts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("marketing_runs.run_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("artifact_key", sa.String(length=128), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("step", sa.String(length=64), nullable=True),
        sa.Column(
            "payload_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "run_id",
            "artifact_key",
            name="uq_marketing_artifacts_run_key",
        ),
    )
    op.create_index(
        "ix_marketing_artifacts_run_id",
        "marketing_artifacts",
        ["run_id"],
    )
    op.create_index(
        "ix_marketing_artifacts_artifact_type",
        "marketing_artifacts",
        ["artifact_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_marketing_artifacts_artifact_type",
        table_name="marketing_artifacts",
    )
    op.drop_index(
        "ix_marketing_artifacts_run_id",
        table_name="marketing_artifacts",
    )
    op.drop_table("marketing_artifacts")

    op.drop_index("ix_marketing_runs_status", table_name="marketing_runs")
    op.drop_index(
        "ix_marketing_runs_workflow_type",
        table_name="marketing_runs",
    )
    op.drop_index("ix_marketing_runs_user_id", table_name="marketing_runs")
    op.drop_table("marketing_runs")
