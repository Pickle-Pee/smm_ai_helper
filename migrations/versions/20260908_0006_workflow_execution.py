"""Fixed workflow execution leases and independent durable Telegram delivery.

Revision ID: 20260908_0006
Revises: 20260908_0005
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260908_0006"
down_revision = "20260908_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "job_executions",
        sa.Column("job_id", sa.String(32), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claim_token", sa.String(32)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("attempts >= 0", name="ck_execution_attempts"),
        sa.CheckConstraint("(claim_token IS NULL) = (lease_until IS NULL)", name="ck_execution_lease"),
    )
    op.create_index("ix_execution_due", "job_executions", ["available_at", "lease_until"])
    op.create_table(
        "workflow_deliveries",
        sa.Column("delivery_id", sa.String(32), primary_key=True),
        sa.Column("job_id", sa.String(32), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), nullable=False),
        sa.Column("part", sa.Integer(), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claim_token", sa.String(32)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("telegram_message_id", sa.BigInteger()),
        sa.Column("error", sa.String(255)),
        sa.UniqueConstraint("job_id", "part", name="uq_delivery_job_part"),
        sa.CheckConstraint("status IN ('pending', 'sending', 'delivered', 'failed')", name="ck_delivery_status"),
        sa.CheckConstraint("attempts >= 0 AND part >= 0", name="ck_delivery_counters"),
        sa.CheckConstraint("(claim_token IS NULL) = (lease_until IS NULL)", name="ck_delivery_lease"),
    )
    op.create_index("ix_delivery_due", "workflow_deliveries", ["status", "available_at"])
    op.create_index("ix_workflow_deliveries_job_id", "workflow_deliveries", ["job_id"])


def downgrade():
    op.drop_table("workflow_deliveries")
    op.drop_table("job_executions")
