"""B2.1 browser login and sessions. Existing users and owners are unchanged."""
import sqlalchemy as sa
from alembic import op

revision = "20261121_0016"
down_revision = "20261114_0015"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE auth_tokens (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ,
            CONSTRAINT ck_auth_token_ttl CHECK
                (created_at < expires_at AND expires_at <= created_at + interval '10 minutes')
        )
    """)
    op.create_index("ix_auth_tokens_user_created", "auth_tokens", ["user_id", "created_at"])
    op.create_index("ix_auth_tokens_expiry", "auth_tokens", ["expires_at"])
    op.execute("""
        CREATE TABLE browser_attempts (
            token_id BIGINT PRIMARY KEY REFERENCES auth_tokens(id) ON DELETE CASCADE,
            cookie_hash VARCHAR(64) NOT NULL UNIQUE,
            code_hash VARCHAR(64) NOT NULL UNIQUE,
            confirmed_at TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE TABLE web_sessions (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash VARCHAR(64) NOT NULL UNIQUE,
            created_at TIMESTAMPTZ NOT NULL,
            idle_expires_at TIMESTAMPTZ NOT NULL,
            absolute_expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            CONSTRAINT ck_web_session_ttl CHECK
                (created_at < idle_expires_at AND idle_expires_at <= absolute_expires_at)
        )
    """)
    op.create_index("ix_web_sessions_idle_expiry", "web_sessions", ["idle_expires_at"])


def downgrade():
    if op.get_bind().scalar(sa.text(
        "SELECT EXISTS (SELECT FROM web_sessions) OR EXISTS (SELECT FROM auth_tokens)"
    )):
        raise RuntimeError("B2.1 downgrade refused while auth records exist")
    op.drop_table("web_sessions")
    op.drop_table("browser_attempts")
    op.drop_table("auth_tokens")
