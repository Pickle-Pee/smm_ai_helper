"""Align legacy timestamp/status nullability with the existing model contracts.

Revision ID: 20260909_0007
Revises: 20260908_0006

Missing historical dates cannot be reconstructed: backfill from the companion
timestamp when present, otherwise use migration time (UTC). Existing dates stay
unchanged. Unknown historical task status remains explicitly 'unknown'.
"""
from alembic import op
import sqlalchemy as sa

revision = "20260909_0007"
down_revision = "20260908_0006"
branch_labels = None
depends_on = None

TIMESTAMPS = {
    "users": ("created_at",), "tasks": ("created_at",),
    "conversations": ("updated_at",), "messages": ("created_at",),
    "url_cache": ("created_at",), "task_sessions": ("created_at", "updated_at"),
    "brand_profiles": ("created_at", "updated_at"),
    "marketing_runs": ("created_at", "updated_at"),
    "marketing_artifacts": ("created_at", "updated_at"),
}


def upgrade():
    for table, columns in TIMESTAMPS.items():
        for column in columns:
            alternatives = ", ".join(columns)
            op.execute(sa.text(f"UPDATE {table} SET {column} = COALESCE({alternatives}, CURRENT_TIMESTAMP AT TIME ZONE 'UTC') WHERE {column} IS NULL"))
            op.alter_column(table, column, existing_type=sa.DateTime(), nullable=False)
    op.execute(sa.text("UPDATE tasks SET status = 'unknown' WHERE status IS NULL"))
    op.alter_column("tasks", "status", existing_type=sa.String(32), nullable=False)


def downgrade():
    # Backfilled values are retained; only the former nullable schema is restored.
    for table, columns in TIMESTAMPS.items():
        for column in columns:
            op.alter_column(table, column, existing_type=sa.DateTime(), nullable=True)
    op.alter_column("tasks", "status", existing_type=sa.String(32), nullable=True)
