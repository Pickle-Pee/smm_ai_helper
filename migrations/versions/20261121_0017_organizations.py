"""B3 tenants and versioned memberships. No legacy data backfill."""
import sqlalchemy as sa
from alembic import op

revision = "20261121_0017"
down_revision = "20261121_0016"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE organizations (
            id UUID PRIMARY KEY,
            name VARCHAR(120) NOT NULL CHECK (length(btrim(name)) > 0),
            kind VARCHAR(8) NOT NULL,
            personal_user_id INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ,
            CONSTRAINT ck_organization_kind CHECK (
                (kind = 'personal' AND personal_user_id IS NOT NULL) OR
                (kind = 'team' AND personal_user_id IS NULL))
        )
    """)
    op.execute("""
        CREATE TABLE memberships (
            org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role VARCHAR(8) NOT NULL CHECK (role IN ('owner','editor','viewer')),
            version BIGINT NOT NULL DEFAULT 1 CHECK (version >= 1),
            joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            revoked_at TIMESTAMPTZ,
            PRIMARY KEY (org_id, user_id)
        )
    """)
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.execute("""
        CREATE FUNCTION membership_access_version() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (NEW.org_id, NEW.user_id) IS DISTINCT FROM (OLD.org_id, OLD.user_id) THEN
                RAISE EXCEPTION 'membership keys are immutable';
            END IF;
            NEW.version := OLD.version;
            IF (NEW.role, NEW.revoked_at) IS DISTINCT FROM (OLD.role, OLD.revoked_at) THEN
                NEW.version := OLD.version + 1;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("CREATE TRIGGER membership_access_version BEFORE UPDATE ON memberships "
               "FOR EACH ROW EXECUTE FUNCTION membership_access_version()")


def downgrade():
    op.execute("LOCK TABLE organizations, memberships IN ACCESS EXCLUSIVE MODE")
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT FROM organizations)")):
        raise RuntimeError("B3 downgrade refused while organizations exist")
    op.drop_table("memberships")
    op.execute("DROP FUNCTION membership_access_version()")
    op.drop_table("organizations")
