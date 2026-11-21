import asyncio
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.config import settings
from app.db import get_session
from app.main import app
from app.models import BrandProfile, Job, TaskSessionRecord, User
from bot.backend import actor_headers
from tests.test_telegram_admission import GENERATION
from tests.test_web_session_http import client
from app.telegram_admission import require_ready_profile
from tests.postgresql_support import mvp_database
from tests.test_web_auth_postgresql import actors


def test_gate_waits_for_committed_brand_and_is_scoped_to_verified_owner(mvp_database, actors, monkeypatch):
    owner, stranger = actors
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_COHORT", frozenset(actors))

    async def admitted(actor):
        async with mvp_database() as db:
            await require_ready_profile(actor, db)

    async def blocked(actor):
        with pytest.raises(HTTPException) as rejection:
            await admitted(actor)
        assert (rejection.value.status_code, rejection.value.detail) == (409, "onboarding_required")

    async def run():
        await blocked(owner)
        try:
            async with mvp_database.begin() as writer:
                user_id = await writer.scalar(select(User.id).where(User.telegram_id == owner))
                writer.add(BrandProfile(user_id=user_id, product_description="Coffee", audience="Neighbors",
                                        goals=["Visitors"]))
                await writer.flush()
                await asyncio.gather(blocked(owner), blocked(stranger))
            await admitted(owner)
            await blocked(stranger)
            monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_COHORT", frozenset({owner}))
            await admitted(stranger)
        finally:
            async with mvp_database.begin() as writer:
                await writer.execute(delete(BrandProfile).where(
                    BrandProfile.user_id.in_(select(User.id).where(User.telegram_id == owner))))

    asyncio.run(run())


def test_all_direct_generation_routes_refuse_an_incomplete_profile(mvp_database, actors, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "onboarding-test-bot")
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_ENABLED", True)
    actor = actors[0]
    session_id = uuid.uuid4().hex

    async def database():
        async with mvp_database() as db:
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_session, database)

    async def run():
        async with mvp_database.begin() as db:
            db.add(TaskSessionRecord(session_id=session_id, user_id=str(actor), agent_type="strategy",
                                     task_description="Old clarification"))
            before = await db.scalar(select(func.count()).select_from(Job))
        try:
            async with client() as bot:
                for method, template in sorted(GENERATION):
                    run_id = "a" * (32 if template.startswith("/workflows/") else 64)
                    path = template.format(run_id=run_id, agent_type="strategy")
                    fields = {"user": {"telegram_id": actor}, "user_id": f"tg:{actor}",
                              "session_id": session_id}
                    response = await bot.request(method, path, headers=actor_headers(actor), json=fields)
                    assert response.status_code == 409, (path, response.text)
                    assert response.json() == {"detail": "onboarding_required"}
            async with mvp_database() as db:
                assert await db.scalar(select(func.count()).select_from(Job)) == before
        finally:
            async with mvp_database.begin() as db:
                await db.execute(delete(TaskSessionRecord).where(TaskSessionRecord.session_id == session_id))

    asyncio.run(run())
