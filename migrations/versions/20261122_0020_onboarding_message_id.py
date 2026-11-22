"""Keep Telegram onboarding answers from replaying as new chat messages."""
from alembic import op
import sqlalchemy as sa


revision = "20261122_0020"
down_revision = "20261121_0019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user_preferred_names", sa.Column("last_onboarding_message_id", sa.BigInteger(), nullable=True))


def downgrade():
    op.drop_column("user_preferred_names", "last_onboarding_message_id")
