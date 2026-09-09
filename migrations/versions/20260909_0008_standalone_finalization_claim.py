"""Fence standalone task execution before provider calls.

Revision ID: 20260909_0008
Revises: 20260909_0007
"""
from alembic import op
import sqlalchemy as sa

revision = "20260909_0008"
down_revision = "20260909_0007"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("task_sessions", sa.Column("finalization_token", sa.String(32), nullable=True))
    op.add_column("task_sessions", sa.Column("finalization_lease_until", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint("ck_task_session_claim_pair", "task_sessions",
                               "(finalization_token IS NULL) = (finalization_lease_until IS NULL)")
    op.create_check_constraint("ck_task_session_completed_unclaimed", "task_sessions",
                               "completed_response IS NULL OR finalization_token IS NULL")


def downgrade():
    # Stop backend requests first: old code cannot honor active execution claims.
    # Saved answers, completed responses and Task history are retained.
    op.drop_constraint("ck_task_session_completed_unclaimed", "task_sessions", type_="check")
    op.drop_constraint("ck_task_session_claim_pair", "task_sessions", type_="check")
    op.drop_column("task_sessions", "finalization_lease_until")
    op.drop_column("task_sessions", "finalization_token")
