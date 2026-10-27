"""Add durable source threads and private-chat active selection (additive rollout)."""
from alembic import op
import sqlalchemy as sa

revision = "20261026_0013"
down_revision = "20261014_0012"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("project_sessions",
        sa.Column("session_id", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("public_id", sa.String(80), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_id", "public_id", name="uq_project_session_owner_source"),
        sa.CheckConstraint("mode IN ('mentor', 'project_chat')", name="ck_project_session_mode"))
    op.create_index("ix_project_sessions_owner_id", "project_sessions", ["owner_id"])
    op.create_table("active_project_bindings",
        sa.Column("actor_id", sa.BigInteger(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("project_sessions.session_id", ondelete="SET NULL"), nullable=True),
        sa.Column("version", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("version >= 0", name="ck_active_project_version"),
        sa.CheckConstraint("actor_id = chat_id AND actor_id > 0", name="ck_active_project_private"))
    op.create_table("project_discussion_turns",
        sa.Column("turn_id", sa.String(32), primary_key=True),
        sa.Column("session_id", sa.String(32), sa.ForeignKey("project_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reply", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("actor_id", "request_key", name="uq_project_turn_actor_request"),
        sa.CheckConstraint("status IN ('running', 'completed', 'unknown')", name="ck_project_turn_status"),
        sa.CheckConstraint("(status = 'completed') = (reply IS NOT NULL)", name="ck_project_turn_result"))
    op.create_index("ix_project_turn_session_created", "project_discussion_turns", ["session_id", "created_at", "turn_id"])
    # Projection scans only owner/type/date metadata before detailed source loading.
    op.create_index("ix_marketing_runs_owner_type_activity", "marketing_runs", ["user_id", "workflow_type", "updated_at", "run_id"])
    op.create_index("ix_tasks_owner_created", "tasks", ["user_id", "created_at", "id"])


def downgrade():
    op.drop_index("ix_tasks_owner_created", table_name="tasks")
    op.drop_index("ix_marketing_runs_owner_type_activity", table_name="marketing_runs")
    op.drop_table("project_discussion_turns")
    op.drop_table("active_project_bindings")
    op.drop_table("project_sessions")
