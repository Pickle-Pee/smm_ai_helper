"""Real PostgreSQL upgrade/downgrade evidence, isolated from durable-job tests."""
import os
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import settings
from tests.postgresql_support import mvp_database


def test_mvp_migration_roundtrip_preserves_legacy_rows_and_matches_models(mvp_database, monkeypatch):
    url = os.environ["MVP_TEST_DATABASE_URL"]  # Fixture validates disposable database first.
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    config = Config("alembic.ini")
    engine = create_engine(url.replace("+asyncpg", "+psycopg2"))
    actor = int(uuid.uuid4().hex[:12], 16)
    user_id = task_id = None
    try:
        command.downgrade(config, "20260908_0005")
        with engine.begin() as db:
            user_id = db.scalar(text("INSERT INTO users (telegram_id, created_at) VALUES (:actor, NULL) RETURNING id"), {"actor": actor})
            task_id = db.scalar(text("INSERT INTO tasks (user_id, agent_type, task_description, status, created_at) VALUES (:owner, 'strategy', 'legacy row', NULL, NULL) RETURNING id"), {"owner": user_id})
            assert not inspect(db).has_table("job_executions")
        command.upgrade(config, "head")
        with engine.connect() as db:
            row = db.execute(text("SELECT status, created_at, task_description FROM tasks WHERE id=:id"), {"id": task_id}).one()
            assert row.status == "unknown" and row.created_at is not None and row.task_description == "legacy row"
            before = row.created_at
            assert {"ck_execution_attempts", "ck_execution_lease"} <= {c["name"] for c in inspect(db).get_check_constraints("job_executions")}
            assert {"ck_delivery_status", "ck_delivery_counters", "ck_delivery_lease"} <= {c["name"] for c in inspect(db).get_check_constraints("workflow_deliveries")}
            assert {"ck_task_session_claim_pair", "ck_task_session_completed_unclaimed"} <= {c["name"] for c in inspect(db).get_check_constraints("task_sessions")}
        command.check(config)  # Full model/schema comparison, including prior foundations.
        command.downgrade(config, "20260908_0006")
        command.upgrade(config, "head")
        with engine.connect() as db:
            assert db.scalar(text("SELECT created_at FROM tasks WHERE id=:id"), {"id": task_id}) == before
    finally:
        command.upgrade(config, "head")
        with engine.begin() as db:
            if task_id: db.execute(text("DELETE FROM tasks WHERE id=:id"), {"id": task_id})
            if user_id: db.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
        engine.dispose()


def test_standalone_claim_migration_preserves_completed_sessions(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", os.environ["MVP_TEST_DATABASE_URL"])
    config = Config("alembic.ini")
    engine = create_engine(settings.DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    session_id = uuid.uuid4().hex
    try:
        command.downgrade(config, "20260909_0007")
        with engine.begin() as db:
            db.execute(text("""INSERT INTO task_sessions
                (session_id, user_id, agent_type, task_description, mode, answers,
                 questions_asked, request_id, created_at, updated_at, completed_response)
                VALUES (:id, 'anonymous', 'strategy', 'legacy completed', 'text',
                        '{"goal":"saved"}', 1, '-', now(), now(), '{"status":"done"}')"""), {"id": session_id})
        command.upgrade(config, "head")
        with engine.connect() as db:
            row = db.execute(text("SELECT * FROM task_sessions WHERE session_id=:id"), {"id": session_id}).one()
            assert row.completed_response == {"status": "done"}
            assert row.answers == {"goal": "saved"}
            assert row.finalization_token is row.finalization_lease_until is None
        command.downgrade(config, "20260909_0007")
        with engine.connect() as db:
            assert db.scalar(text("SELECT completed_response FROM task_sessions WHERE session_id=:id"), {"id": session_id}) == {"status": "done"}
        command.upgrade(config, "head")
        command.check(config)
    finally:
        command.upgrade(config, "head")
        with engine.begin() as db:
            db.execute(text("DELETE FROM task_sessions WHERE session_id=:id"), {"id": session_id})
        engine.dispose()
