"""Store private POSITIONING checkpoints independently from public artifacts."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20261103_0014"
down_revision = "20261026_0013"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "positioning_verifications",
        sa.Column("job_id", sa.String(32), sa.ForeignKey("jobs.job_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("checkpoint", postgresql.JSONB(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("positioning_verifications")
