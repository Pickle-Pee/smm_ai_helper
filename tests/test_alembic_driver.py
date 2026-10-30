"""Exercise both Alembic entrypoints without connecting to a database."""
from contextlib import nullcontext
from pathlib import Path
import runpy
from types import SimpleNamespace

from alembic import context
from alembic.config import Config
import pytest
import sqlalchemy
from sqlalchemy.engine import make_url

from app.config import settings


@pytest.mark.parametrize("offline", [True, False], ids=["offline", "online"])
@pytest.mark.parametrize("prefix", [
    "postgresql+asyncpg://", "postgresql+psycopg://",
])
def test_alembic_uses_installed_sync_driver_and_preserves_url(monkeypatch, offline, prefix):
    # Encoded credentials, repeated options and escaped percent signs must survive.
    suffix = "user:p%40ss%25word@localhost:5432/disposable?sslmode=require&application_name=test%20migration&options=-csearch_path%3Dpublic"
    url = prefix + suffix
    expected = "postgresql+psycopg://" + suffix
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    monkeypatch.setattr(context, "config", Config(), raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: offline)
    configured = {}
    monkeypatch.setattr(context, "configure", lambda **kw: configured.update(kw))
    monkeypatch.setattr(context, "begin_transaction", nullcontext)
    ran = []
    monkeypatch.setattr(context, "run_migrations", lambda: ran.append(True))
    real_factory = sqlalchemy.engine_from_config
    engines = []
    connection = object()

    def engine_factory(configuration, **kwargs):
        # Load the real synchronous DBAPI selected by current master.
        engine = real_factory(configuration, **kwargs)
        engines.append(engine)
        assert engine.dialect.driver == "psycopg"
        assert engine.dialect.dbapi.__name__ == "psycopg"
        assert engine.url == make_url(expected)
        return SimpleNamespace(connect=lambda: nullcontext(connection))

    monkeypatch.setattr(sqlalchemy, "engine_from_config", engine_factory)
    try:
        runpy.run_path(str(Path(__file__).parents[1] / "migrations" / "env.py"))
        assert ran == [True]
        assert settings.DATABASE_URL == url
        if offline:
            assert configured["url"] == expected
            assert configured["literal_binds"] is True
            assert not engines
        else:
            assert configured["connection"] is connection
            assert configured["compare_type"] is True
    finally:
        for engine in engines:
            engine.dispose()


def test_non_postgresql_url_is_preserved(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "sqlite:///disposable.db")
    monkeypatch.setattr(context, "config", Config(), raising=False)
    monkeypatch.setattr(context, "is_offline_mode", lambda: True)
    configured = {}
    monkeypatch.setattr(context, "configure", lambda **kw: configured.update(kw))
    monkeypatch.setattr(context, "begin_transaction", nullcontext)
    monkeypatch.setattr(context, "run_migrations", lambda: None)
    runpy.run_path(str(Path(__file__).parents[1] / "migrations" / "env.py"))
    assert configured["url"] == "sqlite:///disposable.db"
