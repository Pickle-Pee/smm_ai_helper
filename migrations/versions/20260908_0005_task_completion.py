"""Retain atomic, replayable standalone task outcomes.

Revision ID: 20260908_0005
Revises: 20260825_0004
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260908_0005"
down_revision = "20260825_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("task_sessions", sa.Column(
        "completed_response", postgresql.JSONB(none_as_null=True), nullable=True,
    ))


def downgrade():
    op.drop_column("task_sessions", "completed_response")
