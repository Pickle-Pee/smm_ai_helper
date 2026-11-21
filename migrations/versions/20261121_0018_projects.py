"""Personal workspace projects and independent brand profiles."""
from alembic import op

revision = "20261121_0018"
down_revision = "20261121_0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_unique_constraint("uq_org_personal_pair", "organizations", ["id", "personal_user_id"])
    op.execute("""
        CREATE TABLE projects (
            id uuid PRIMARY KEY,
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            default_for_user integer UNIQUE,
            name varchar(120) NOT NULL,
            status varchar(8) NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','archived')),
            color varchar(8) CHECK (color IN ('teal','violet','coral','amber','blue','green')),
            version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
            created_by integer NOT NULL REFERENCES users(id) DEFERRABLE INITIALLY DEFERRED,
            request_key uuid, request_hash varchar(64),
            created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE(id, org_id), UNIQUE(created_by, request_key),
            FOREIGN KEY(org_id, default_for_user) REFERENCES organizations(id, personal_user_id)
        )
    """)
    op.create_index("ix_projects_org_updated", "projects", ["org_id", "updated_at", "id"])
    op.execute("""
        CREATE TABLE project_brands (
            project_id uuid PRIMARY KEY, org_id uuid NOT NULL,
            version bigint NOT NULL DEFAULT 1 CHECK (version > 0),
            brand_name varchar(255), product_description varchar(4000), audience varchar(4000), tone varchar(4000),
            goals jsonb NOT NULL DEFAULT '[]', channels jsonb NOT NULL DEFAULT '[]', extra_json jsonb NOT NULL DEFAULT '{}',
            source_profile_id integer, imported_by integer REFERENCES users(id) DEFERRABLE INITIALLY DEFERRED, imported_at timestamptz,
            updated_by integer REFERENCES users(id) DEFERRABLE INITIALLY DEFERRED, updated_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY(project_id, org_id) REFERENCES projects(id, org_id) ON DELETE CASCADE,
            CHECK ((imported_at IS NULL) = (imported_by IS NULL))
        )
    """)
    op.execute("""
        CREATE FUNCTION forbid_project_move() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (NEW.org_id, NEW.default_for_user) IS DISTINCT FROM (OLD.org_id, OLD.default_for_user) THEN
                RAISE EXCEPTION 'immutable project ownership' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("CREATE TRIGGER immutable_project_owner BEFORE UPDATE ON projects "
               "FOR EACH ROW EXECUTE FUNCTION forbid_project_move()")


def downgrade():
    op.execute("DO $$ BEGIN IF EXISTS (SELECT FROM projects) THEN "
               "RAISE EXCEPTION 'refusing to discard web projects'; END IF; END $$")
    op.drop_table("project_brands")
    op.drop_table("projects")
    op.execute("DROP FUNCTION forbid_project_move()")
    op.drop_constraint("uq_org_personal_pair", "organizations", type_="unique")
