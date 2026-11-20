"""Real PostgreSQL evidence for migration 20261114_0015 (B1a identity foundation).

Upgrades from the real production head ``20261103_0014`` with legacy rows, checks
the backfill, ownership preservation, repeated upgrade, the refusing downgrade and
an aborting preflight. Disposable ``smm_mvp_test`` database only.
"""
import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.config import settings
from tests.postgresql_support import mvp_database

PREVIOUS, B1A = "20261103_0014", "20261114_0015"


def test_b1a_is_the_single_head_directly_after_production_0014():
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    assert script.get_heads() == [B1A]
    assert script.get_revision(B1A).down_revision == PREVIOUS


@pytest.fixture
def migration(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", os.environ["MVP_TEST_DATABASE_URL"])
    config = Config("alembic.ini")
    engine = create_engine(settings.DATABASE_URL.replace("+asyncpg", "+psycopg"))
    try:
        yield config, engine
    finally:
        command.upgrade(config, "head")
        engine.dispose()


def telegram_nullable(db):
    return next(c for c in inspect(db).get_columns("users") if c["name"] == "telegram_id")["nullable"]


def version(engine):
    with engine.connect() as db:
        return db.scalar(text("SELECT version_num FROM alembic_version"))


def ownership(engine, user_ids, run_ids):
    with engine.connect() as db:
        return (
            db.execute(text("SELECT id, telegram_id FROM users WHERE id = ANY(:ids) ORDER BY id"), {"ids": user_ids}).all(),
            db.execute(text("SELECT id, user_id FROM tasks WHERE user_id = ANY(:ids) ORDER BY id"), {"ids": user_ids}).all(),
            db.execute(text("SELECT id, user_id FROM brand_profiles WHERE user_id = ANY(:ids) ORDER BY id"), {"ids": user_ids}).all(),
            db.execute(text("SELECT run_id, user_id FROM marketing_runs WHERE run_id = ANY(:ids) ORDER BY run_id"), {"ids": run_ids}).all(),
        )


def identities(engine, user_ids):
    with engine.connect() as db:
        return db.execute(text(
            "SELECT e.user_id, e.provider, e.subject, e.telegram_id, e.verified_at = (u.created_at AT TIME ZONE 'UTC') "
            "FROM external_identities e JOIN users u ON u.id = e.user_id "
            "WHERE e.user_id = ANY(:ids) ORDER BY e.user_id"), {"ids": user_ids}).all()


def test_upgrade_backfills_legacy_users_without_touching_ownership(migration):
    config, engine = migration
    actors = [int(uuid.uuid4().hex[:12], 16) + 1 for _ in range(3)]
    run_ids = [uuid.uuid4().hex for _ in actors]
    user_ids = []
    try:
        command.downgrade(config, PREVIOUS)
        with engine.begin() as db:
            assert not inspect(db).has_table("external_identities")
            assert not telegram_nullable(db)
            for actor, run_id in zip(actors, run_ids):
                user_id = db.scalar(text("INSERT INTO users (telegram_id, username, created_at) "
                                         "VALUES (:a, 'legacy', now() - interval '30 days') RETURNING id"), {"a": actor})
                user_ids.append(user_id)
                db.execute(text("INSERT INTO tasks (user_id, agent_type, task_description, status, created_at) "
                                "VALUES (:u, 'strategy', 'history', 'done', now())"), {"u": user_id})
                db.execute(text("INSERT INTO brand_profiles (user_id, brand_name, created_at, updated_at) "
                                "VALUES (:u, 'brand', now(), now())"), {"u": user_id})
                db.execute(text("INSERT INTO marketing_runs (run_id, user_id, workflow_type, status, created_at, updated_at) "
                                "VALUES (:r, :u, 'marketing_mvp.v1', 'completed', now(), now())"), {"r": run_id, "u": user_id})
        before = ownership(engine, user_ids, run_ids)

        command.upgrade(config, "head")
        command.check(config)
        assert version(engine) == B1A
        assert ownership(engine, user_ids, run_ids) == before
        expected = [(user_id, "telegram", str(actor), actor, True) for user_id, actor in zip(user_ids, actors)]
        assert identities(engine, user_ids) == expected
        with engine.connect() as db:
            assert telegram_nullable(db)
            assert db.scalar(text("SELECT count(*) FROM users u WHERE u.telegram_id IS NOT NULL AND NOT EXISTS ("
                                  "SELECT 1 FROM external_identities e WHERE e.user_id = u.id "
                                  "AND e.telegram_id = u.telegram_id)")) == 0

        # Repeated migration (rollback + re-apply) keeps ids and creates no duplicates.
        command.downgrade(config, PREVIOUS)
        assert ownership(engine, user_ids, run_ids) == before
        command.upgrade(config, "head")
        command.check(config)
        assert ownership(engine, user_ids, run_ids) == before
        assert identities(engine, user_ids) == expected
        with engine.connect() as db:
            assert db.scalar(text("SELECT count(*) - count(DISTINCT (provider, subject)) FROM external_identities")) == 0
    finally:
        command.upgrade(config, "head")
        with engine.begin() as db:
            for table in ("tasks", "brand_profiles", "marketing_runs"):
                db.execute(text(f"DELETE FROM {table} WHERE user_id = ANY(:ids)"), {"ids": user_ids})
            db.execute(text("DELETE FROM users WHERE id = ANY(:ids)"), {"ids": user_ids})


def test_downgrade_refuses_to_lose_web_only_users_and_rolls_back(migration):
    config, engine = migration
    command.upgrade(config, "head")
    with engine.begin() as db:
        web = db.scalar(text("INSERT INTO users (telegram_id, created_at) VALUES (NULL, now()) RETURNING id"))
    try:
        with pytest.raises(RuntimeError, match="downgrade refused"):
            command.downgrade(config, PREVIOUS)
        assert version(engine) == B1A
        with engine.connect() as db:
            assert inspect(db).has_table("external_identities")
            assert db.scalar(text("SELECT count(*) FROM users WHERE id = :id"), {"id": web}) == 1
    finally:
        with engine.begin() as db:
            db.execute(text("DELETE FROM users WHERE id = :id"), {"id": web})


def test_upgrade_aborts_atomically_on_a_non_canonical_legacy_telegram_id(migration):
    config, engine = migration
    command.downgrade(config, PREVIOUS)
    with engine.begin() as db:
        bad = db.scalar(text("INSERT INTO users (telegram_id, created_at) VALUES (-42, now()) RETURNING id"))
    try:
        with pytest.raises(RuntimeError, match="non-positive telegram_id"):
            command.upgrade(config, "head")
        assert version(engine) == PREVIOUS
        with engine.connect() as db:
            assert not inspect(db).has_table("external_identities")
            assert db.scalar(text("SELECT telegram_id FROM users WHERE id = :id"), {"id": bad}) == -42
    finally:
        with engine.begin() as db:
            db.execute(text("DELETE FROM users WHERE id = :id"), {"id": bad})
