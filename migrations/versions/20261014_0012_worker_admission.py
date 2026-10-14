"""Durable worker claim admission (legacy workers do not honor this barrier)."""
from alembic import op
import sqlalchemy as sa

revision = "20261014_0012"
down_revision = "20261006_0011"
branch_labels = None
depends_on = None


def upgrade():
    table = op.create_table("worker_admission",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("epoch", sa.BigInteger(), nullable=False, server_default="0"),
        sa.CheckConstraint("id = 'workers'", name="ck_worker_admission_singleton"),
        sa.CheckConstraint("epoch >= 0", name="ck_worker_admission_epoch"))
    # Compatibility default, NOT a bootstrap barrier for old binaries.
    op.bulk_insert(table, [{"id": "workers", "paused": False, "epoch": 0}])
    op.create_table("worker_attempts",
        sa.Column("job_id", sa.String(32), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("claim_token", sa.String(32), primary_key=True))


def downgrade():
    op.drop_table("worker_attempts")
    op.drop_table("worker_admission")
