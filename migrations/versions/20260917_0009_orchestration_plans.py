"""Add immutable compiled execution plan revisions.

Revision ID: 20260917_0009
Revises: 20260909_0008
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260917_0009"
down_revision = "20260909_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "orchestration_plans",
        sa.Column("run_id", sa.String(64), sa.ForeignKey("marketing_runs.run_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("source_plan_id", sa.String(64), nullable=False),
        sa.Column("compiled_plan_fingerprint", sa.String(64), nullable=False),
        sa.Column("registry_version", sa.String(32), nullable=False),
        sa.Column("compiled_plan_json", JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("revision > 0", name="ck_orchestration_revision"),
        sa.CheckConstraint("status IN ('active', 'superseded')", name="ck_orchestration_plan_status"),
        sa.CheckConstraint("jsonb_typeof(compiled_plan_json) = 'object'", name="ck_orchestration_plan_object"),
        sa.UniqueConstraint("run_id", "source_plan_id", name="uq_orchestration_source"),
        sa.UniqueConstraint("run_id", "compiled_plan_fingerprint", name="uq_orchestration_fingerprint"),
    )
    op.create_index("uq_orchestration_active", "orchestration_plans", ["run_id"], unique=True,
                    postgresql_where=sa.text("status = 'active'"))


def downgrade():
    # Stop internal graph workers first. Fixed workflow tables/data are untouched.
    op.drop_table("orchestration_plans")
