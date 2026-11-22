"""Add password storage for verified email identities without changing owners."""
import sqlalchemy as sa
from alembic import op

revision = "20261122_0021"
down_revision = "20261122_0020"
branch_labels = None
depends_on = None


def upgrade():
    # Fail atomically on conflicting reserved email identities. Never rewrite evidence.
    op.create_check_constraint(
        "ck_external_identities_email_subject", "external_identities",
        sa.text("""provider <> 'email' OR (subject COLLATE "C" ~ '^[!-~]{3,254}$' AND subject = lower(subject COLLATE "C"))"""),
    )
    op.create_index(
        "uq_external_identities_email_user", "external_identities", ["user_id"], unique=True,
        postgresql_where=sa.text("provider = 'email'"),
    )
    op.create_table(
        "email_credentials",
        sa.Column("email", sa.String(254), primary_key=True),
        sa.Column("identity_provider", sa.String(64), nullable=False, server_default="email"),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["identity_provider", "email"], ["external_identities.provider", "external_identities.subject"],
            name="fk_email_credentials_verified_identity", ondelete="CASCADE",
        ),
        sa.CheckConstraint("identity_provider = 'email'", name="ck_email_credentials_provider"),
        sa.CheckConstraint("password_hash LIKE '$argon2id$%'", name="ck_email_credentials_argon2id"),
    )


def downgrade():
    op.execute("LOCK TABLE email_credentials IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT FROM email_credentials)")):
        raise RuntimeError("AUTH-01 downgrade refused while email credentials exist")
    op.drop_table("email_credentials")
    op.drop_index("uq_external_identities_email_user", table_name="external_identities")
    op.drop_constraint("ck_external_identities_email_subject", "external_identities", type_="check")
