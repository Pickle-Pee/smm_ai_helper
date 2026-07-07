"""initial schema

Revision ID: 20260707_0001
Revises:
Create Date: 2026-07-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260707_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("telegram_id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"], unique=True)

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("agent_type", sa.String(length=50), nullable=False),
        sa.Column("task_description", sa.Text(), nullable=False),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_tasks_agent_type", "tasks", ["agent_type"])

    op.create_table(
        "conversations",
        sa.Column("user_id", sa.String(length=128), primary_key=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("facts_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(length=128), sa.ForeignKey("conversations.user_id"), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_messages_user_id", "messages", ["user_id"])

    op.create_table(
        "url_cache",
        sa.Column("url", sa.String(length=2048), primary_key=True),
        sa.Column("extracted_text_hash", sa.String(length=128), nullable=False),
        sa.Column("summary_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_url_cache_expires_at", "url_cache", ["expires_at"])

    op.create_table(
        "task_sessions",
        sa.Column("session_id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("agent_type", sa.String(length=50), nullable=False),
        sa.Column("task_description", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("questions_asked", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_task_sessions_user_id", "task_sessions", ["user_id"])
    op.create_index("ix_task_sessions_agent_type", "task_sessions", ["agent_type"])


def downgrade() -> None:
    # Intentionally left empty for the first baseline migration.
    # Existing MVP databases may already contain these tables from create_all.
    pass
