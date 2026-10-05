"""Persist exact owned-source confirmation snapshots.

Revision ID: 20261006_0010
Revises: 20260917_0009
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261006_0010"
down_revision = "20260917_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("owned_product_snapshots",
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("request_key", sa.String(128), primary_key=True),
        sa.Column("snapshot_id", sa.String(128), primary_key=True),
        sa.Column("owned_site_url", sa.String(2048), nullable=False),
        sa.Column("snapshot_json", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("jsonb_typeof(snapshot_json) = 'object'", name="ck_owned_snapshot_object"))


def downgrade():
    op.drop_table("owned_product_snapshots")
