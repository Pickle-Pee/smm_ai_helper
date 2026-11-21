"""Persist the name a user chooses for onboarding."""
import sqlalchemy as sa
from alembic import op

revision = "20261121_0019"
down_revision = "20261121_0018"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_preferred_names",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("display_name", sa.String(100), nullable=False),
    )


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS (SELECT FROM user_preferred_names) THEN "
               "RAISE EXCEPTION 'refusing to discard preferred names'; END IF; END $$")
    op.drop_table("user_preferred_names")
