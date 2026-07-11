"""add brand profiles

Revision ID: 20260711_0002
Revises: 20260707_0001
Create Date: 2026-07-11
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260711_0002"
down_revision = "20260707_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "brand_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("brand_name", sa.String(length=255), nullable=True),
        sa.Column("product_description", sa.Text(), nullable=True),
        sa.Column("audience", sa.Text(), nullable=True),
        sa.Column("tone", sa.Text(), nullable=True),
        sa.Column("goals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("channels", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("extra_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(
        "ix_brand_profiles_user_id",
        "brand_profiles",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_brand_profiles_user_id", table_name="brand_profiles")
    op.drop_table("brand_profiles")
