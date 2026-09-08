"""Shared explicitly disposable MVP database support. No external providers."""
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings


@pytest.fixture(scope="module")
def mvp_database():
    url = os.getenv("MVP_TEST_DATABASE_URL")
    if not url:
        pytest.skip("MVP_TEST_DATABASE_URL is not configured (disposable PostgreSQL required)")
    if "smm_mvp_test" not in (make_url(url).database or ""):
        pytest.fail("Refusing migration tests outside an explicitly disposable smm_mvp_test database")
    previous = settings.DATABASE_URL
    settings.DATABASE_URL = url
    try:
        command.upgrade(Config("alembic.ini"), "head")
    finally:
        settings.DATABASE_URL = previous
    engine = create_async_engine(url, poolclass=NullPool)
    return async_sessionmaker(engine, expire_on_commit=False)
