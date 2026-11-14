"""B1a identity foundation: nullable users.telegram_id and verified external identities.

Revision ID: 20261114_0015
Revises: 20261103_0014

Expand-only. ``users.id`` stays the single internal principal; no user row,
user id, Telegram id or owner reference is rewritten.

* ``users.telegram_id`` becomes nullable (a future web-only user has NULL, never
  an invented id). Uniqueness of non-NULL ids is kept by the existing
  ``users_telegram_id_key`` constraint and ``ix_users_telegram_id`` index.
* ``external_identities`` stores verified identities, ``UNIQUE(provider, subject)``.
  A Telegram row also carries ``telegram_id`` and a composite FK to
  ``users(id, telegram_id)``: it can only point at the user that owns exactly
  that Telegram id, so one Telegram identity can never belong to two users.
* Every existing Telegram user is backfilled idempotently (``ON CONFLICT DO
  NOTHING``) and verified; any inconsistency aborts the whole migration.
* New Telegram users get their identity from an AFTER INSERT trigger in the
  same transaction, so existing bot/Copilot/workflow creation paths stay
  unchanged. ``users.telegram_id`` is immutable once written: B1a enables no
  linking or merging (Web API v2 D17/OQ-5 and §5.3 keep that deferred).

Downgrade refuses to run while web-only users or non-Telegram identities
exist, because restoring NOT NULL or dropping them would lose data.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261114_0015"
down_revision = "20261103_0014"
branch_labels = None
depends_on = None

PROVIDER_CHECK = "provider ~ '^(telegram|email|oidc:[a-z0-9][a-z0-9._-]{0,58})$'"
SUBJECT_CHECK = (
    "CASE WHEN provider = 'telegram' "
    "THEN telegram_id IS NOT NULL AND telegram_id > 0 AND subject = telegram_id::text "
    "ELSE telegram_id IS NULL AND length(subject) BETWEEN 1 AND 255 AND subject = btrim(subject) END"
)

MIRROR_FUNCTION = """
CREATE FUNCTION external_identities_mirror_telegram() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    -- A Telegram actor reaches users only through the authenticated bot boundary.
    INSERT INTO external_identities (user_id, provider, subject, telegram_id, verified_at, created_at)
    VALUES (NEW.id, 'telegram', NEW.telegram_id::text, NEW.telegram_id, now(), now());
    RETURN NULL;
END
$$
"""

IMMUTABLE_FUNCTION = """
CREATE FUNCTION users_telegram_id_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'users.telegram_id is immutable; Telegram identity linking is not enabled'
        USING ERRCODE = 'restrict_violation';
END
$$
"""

BACKFILL = """
INSERT INTO external_identities (user_id, provider, subject, telegram_id, verified_at, created_at)
SELECT id, 'telegram', telegram_id::text, telegram_id, created_at AT TIME ZONE 'UTC', now()
FROM users
WHERE telegram_id IS NOT NULL
ON CONFLICT (provider, subject) DO NOTHING
"""

UNMATCHED = """
SELECT count(*) FROM users AS u
WHERE u.telegram_id IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM external_identities AS e
    WHERE e.provider = 'telegram' AND e.subject = u.telegram_id::text
      AND e.user_id = u.id AND e.telegram_id = u.telegram_id)
"""


def _count(sql: str) -> int:
    return op.get_bind().scalar(sa.text(sql))


def upgrade():
    invalid = _count("SELECT count(*) FROM users WHERE telegram_id <= 0")
    if invalid:
        raise RuntimeError(f"B1a backfill aborted: {invalid} users have a non-positive telegram_id")

    op.alter_column("users", "telegram_id", existing_type=sa.BigInteger(), nullable=True)
    op.create_unique_constraint("uq_users_id_telegram_id", "users", ["id", "telegram_id"])
    op.create_table(
        "external_identities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_external_identities_user_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["user_id", "telegram_id"], ["users.id", "users.telegram_id"],
            name="fk_external_identities_user_telegram", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("provider", "subject", name="uq_external_identities_provider_subject"),
        sa.CheckConstraint(PROVIDER_CHECK, name="ck_external_identities_provider"),
        sa.CheckConstraint(SUBJECT_CHECK, name="ck_external_identities_subject"),
    )
    op.create_index("ix_external_identities_user_id", "external_identities", ["user_id"])

    # The ALTER above holds ACCESS EXCLUSIVE on users until commit, so no user can
    # be inserted between the backfill and the trigger becoming active.
    op.execute(sa.text(MIRROR_FUNCTION))
    op.execute(sa.text(
        "CREATE TRIGGER users_mirror_telegram_identity AFTER INSERT ON users "
        "FOR EACH ROW WHEN (NEW.telegram_id IS NOT NULL) "
        "EXECUTE FUNCTION external_identities_mirror_telegram()"
    ))
    op.execute(sa.text(IMMUTABLE_FUNCTION))
    op.execute(sa.text(
        "CREATE TRIGGER users_telegram_id_immutable BEFORE UPDATE OF telegram_id ON users "
        "FOR EACH ROW WHEN (OLD.telegram_id IS DISTINCT FROM NEW.telegram_id) "
        "EXECUTE FUNCTION users_telegram_id_immutable()"
    ))

    op.execute(sa.text(BACKFILL))
    unmatched = _count(UNMATCHED)
    if unmatched:
        raise RuntimeError(f"B1a backfill aborted: {unmatched} Telegram users lack their own identity")


def downgrade():
    web_only = _count("SELECT count(*) FROM users WHERE telegram_id IS NULL")
    other = _count("SELECT count(*) FROM external_identities WHERE provider <> 'telegram'")
    if web_only or other:
        raise RuntimeError(
            f"B1a downgrade refused: {web_only} users without telegram_id and {other} "
            "non-Telegram identities would be lost; migrate them explicitly first"
        )
    op.execute(sa.text("DROP TRIGGER users_telegram_id_immutable ON users"))
    op.execute(sa.text("DROP FUNCTION users_telegram_id_immutable()"))
    op.execute(sa.text("DROP TRIGGER users_mirror_telegram_identity ON users"))
    op.execute(sa.text("DROP FUNCTION external_identities_mirror_telegram()"))
    # Telegram identities are fully derivable from users.telegram_id.
    op.drop_index("ix_external_identities_user_id", table_name="external_identities")
    op.drop_table("external_identities")
    op.drop_constraint("uq_users_id_telegram_id", "users", type_="unique")
    op.alter_column("users", "telegram_id", existing_type=sa.BigInteger(), nullable=False)
