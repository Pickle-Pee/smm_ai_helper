import os
import uuid

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import settings
from tests.postgresql_support import mvp_database


def test_graph_migration_roundtrip_preserves_existing_run(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", os.environ["MVP_TEST_DATABASE_URL"])
    config = Config("alembic.ini")
    engine = create_engine(settings.DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    rid = uuid.uuid4().hex
    try:
        command.downgrade(config, "20260909_0008")
        with engine.begin() as session:
            assert not inspect(session).has_table("orchestration_plans")
            session.execute(text("INSERT INTO marketing_runs (run_id, workflow_type, status, created_at, updated_at) VALUES (:rid, 'marketing_mvp.v1', 'completed', now(), now())"), {"rid": rid})
        command.upgrade(config, "head")
        command.check(config)
        with engine.connect() as session:
            assert inspect(session).has_table("orchestration_plans")
            assert session.scalar(text("SELECT status FROM marketing_runs WHERE run_id=:rid"), {"rid": rid}) == "completed"
        command.downgrade(config, "-1")
        command.upgrade(config, "head")
        command.check(config)
    finally:
        command.upgrade(config, "head")
        with engine.begin() as session:
            session.execute(text("DELETE FROM marketing_runs WHERE run_id=:rid"), {"rid": rid})
        engine.dispose()
