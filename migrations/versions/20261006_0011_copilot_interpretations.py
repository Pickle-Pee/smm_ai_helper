"""Persist immutable validated Copilot message interpretations.

Revision ID: 20261006_0011
Revises: 20261006_0010
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261006_0011"
down_revision = "20261006_0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("copilot_interpretations",
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("request_key", sa.String(128), primary_key=True),
        sa.Column("message_fingerprint", sa.String(64), primary_key=True),
        sa.Column("interpretation_json", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("jsonb_typeof(interpretation_json) = 'object'", name="ck_copilot_interpretation_object"),
        sa.CheckConstraint("message_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_copilot_message_fingerprint"))


def downgrade():
    op.drop_table("copilot_interpretations")
