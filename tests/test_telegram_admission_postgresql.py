import asyncio
import uuid
from unittest.mock import AsyncMock

import httpx

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.config import settings
from app.db import get_session
from app.main import app
from app.models import BrandProfile, Job, Task, TaskSessionRecord, User
from app.routers.agents import agent_runner
from app.routers.images import image_orchestrator
from app.routers.tasks import task_pipeline
from app.services.brand_profile_service import BrandProfileService
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
            monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_COHORT", frozenset())
            await admitted(stranger)
        finally:
            async with mvp_database.begin() as writer:
                await writer.execute(delete(BrandProfile).where(
                    BrandProfile.user_id.in_(select(User.id).where(User.telegram_id == owner))))

    asyncio.run(run())


def test_all_direct_generation_routes_refuse_an_incomplete_profile(mvp_database, actors, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "onboarding-test-bot")
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_ENABLED", True)
    network = AsyncMock(side_effect=AssertionError("External HTTP is prohibited"))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", network)
    actor = actors[0]
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_MODE", "all-users")
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_COHORT", frozenset())
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
            network.assert_not_awaited()
        finally:
            async with mvp_database.begin() as db:
                await db.execute(delete(TaskSessionRecord).where(TaskSessionRecord.session_id == session_id))

    asyncio.run(run())

def test_valid_generation_reaches_fake_only_for_ready_or_out_of_cohort_users(mvp_database, actors, monkeypatch):
    owner, outside = actors
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "onboarding-test-bot")
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_COHORT", frozenset({owner}))
    generate = AsyncMock(return_value={"mode": "fake", "preset_id": "offline", "image_ids": ["offline"]})
    monkeypatch.setattr(image_orchestrator, "generate", generate)

    async def database():
        async with mvp_database() as db:
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_session, database)

    async def run():
        async with client() as bot:
            async def request(actor):
                return await bot.post("/images/generate", headers=actor_headers(actor), json={"message": "Sample"})

            assert (await request(owner)).status_code == 409
            generate.assert_not_awaited()
            async with mvp_database.begin() as db:
                uid = await db.scalar(select(User.id).where(User.telegram_id == owner))
                db.add(BrandProfile(user_id=uid, product_description="Coffee", audience="Neighbors",
                                    goals=["Visitors"]))
            try:
                # No preferred-name row is needed for server admission.
                assert (await request(owner)).status_code == 200
                assert (await request(outside)).status_code == 200
                assert generate.await_count == 2
            finally:
                async with mvp_database.begin() as db:
                    await db.execute(delete(BrandProfile).where(BrandProfile.user_id == uid))

    asyncio.run(run())


def test_legacy_generation_uses_only_current_owner_brand_as_prompt_defaults(mvp_database, actors, monkeypatch):
    owner, other = actors
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "legacy-brand-test")
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_MODE", "all-users")
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://api.openai.com/v1")
    network = AsyncMock(side_effect=AssertionError("External HTTP is prohibited"))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", network)

    result = {"content": "Fake result", "confidence": "high"}
    direct_agent = AsyncMock(return_value=result)
    task_agent = AsyncMock(return_value=result)
    image = AsyncMock(return_value={"mode": "fake", "preset_id": "offline", "image_ids": ["offline"]})
    task_image = AsyncMock(return_value={"url": "/images/offline.png"})
    decision = {"needs_clarification": False, "model": "offline", "max_output_tokens": 100}
    route = AsyncMock(side_effect=[
        ({**decision, "needs_clarification": True,
          "next_questions": [{"key": "detail", "question": "Specify a detail"}]}, {}),
        (decision, {}),
    ])
    monkeypatch.setattr(agent_runner, "run", direct_agent)
    monkeypatch.setattr(task_pipeline.agent_runner, "run", task_agent)
    monkeypatch.setattr(task_pipeline.task_router, "route", route)
    monkeypatch.setattr(image_orchestrator, "generate", image)
    monkeypatch.setattr(task_pipeline.task_image_service.image_orchestrator, "generate", task_image)

    async def database():
        async with mvp_database() as db:
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_session, database)

    async def run():
        brand = {"product_description": "Coffee", "audience": "Neighbors", "goals": ["Visitors"]}
        updated = {"product_description": "Tea", "audience": "Neighbors", "goals": ["Visitors"]}
        other_brand = {"product_description": "Flowers", "audience": "Gift shoppers", "goals": ["Sales"]}
        async with mvp_database.begin() as db:
            owner_id = await db.scalar(select(User.id).where(User.telegram_id == owner))
            other_id = await db.scalar(select(User.id).where(User.telegram_id == other))
            profile = BrandProfile(user_id=owner_id, **brand, tone="Personal",
                                   extra_json={"private": "Do not send"})
            db.add_all([profile, BrandProfile(user_id=other_id, **other_brand)])
        session_id = None
        try:
            async with client() as bot:
                request = {"user": {"telegram_id": owner}, "agent_type": "strategy",
                           "task_description": "Synthetic input", "answers": {"audience": "Local buyers"}}
                response = await bot.post("/agents/strategy/run", headers=actor_headers(owner), json=request)
                assert response.status_code == 200, response.text
                assert direct_agent.await_args.kwargs["answers"] == {**brand, "audience": "Local buyers"}

                response = await bot.post("/tasks/start", headers=actor_headers(owner),
                                          json={**request, "mode": "text+image"})
                assert response.status_code == 200 and response.json()["status"] == "need_info", response.text
                session_id = response.json()["session_id"]
                assert route.await_args.args[-1] == {**brand, "audience": "Local buyers"}

                async with mvp_database.begin() as db:
                    current = await BrandProfileService.get_by_user_id(db, owner_id)
                    current.product_description = "Tea"

                response = await bot.post("/tasks/answer", headers=actor_headers(owner),
                                          json={"session_id": session_id, "key": "detail", "value": "Synthetic detail"})
                assert response.status_code == 200 and response.json()["status"] == "done", response.text
                assert task_agent.await_args.kwargs["answers"] == {
                    **updated, "audience": "Local buyers", "detail": "Synthetic detail",
                }
                assert task_image.await_args.kwargs["brand"] == updated

                for actor, expected in ((owner, updated), (other, other_brand)):
                    response = await bot.post("/images/generate", headers=actor_headers(actor), json={"message": "Sample"})
                    assert response.status_code == 200, response.text
                    assert image.await_args.kwargs["brand"] == expected
                monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://alternative.example/v1")
                response = await bot.post("/images/generate", headers=actor_headers(owner), json={"message": "Sample"})
                assert response.status_code == 200, response.text
                assert image.await_args.kwargs["brand"] is None

            async with mvp_database() as db:
                session = await db.get(TaskSessionRecord, session_id)
                assert session.answers == {"audience": "Local buyers", "detail": "Synthetic detail"}
                saved = (await db.scalars(select(Task).where(Task.user_id == owner_id))).all()
                assert sorted((item.answers for item in saved), key=len) == [
                    {"audience": "Local buyers"}, {"audience": "Local buyers", "detail": "Synthetic detail"},
                ]
            network.assert_not_awaited()
        finally:
            async with mvp_database.begin() as db:
                if session_id:
                    await db.execute(delete(TaskSessionRecord).where(TaskSessionRecord.session_id == session_id))
                await db.execute(delete(Task).where(Task.user_id == owner_id))
                await db.execute(delete(BrandProfile).where(BrandProfile.user_id.in_([owner_id, other_id])))

    asyncio.run(run())
