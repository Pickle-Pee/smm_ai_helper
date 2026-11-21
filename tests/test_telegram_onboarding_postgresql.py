import asyncio

from sqlalchemy import delete, select

from app.config import settings
from app.db import get_session
from app.main import app
from app.models import BrandProfile, User, UserPreferredName
from app.routers.workflows import workflow
from bot.backend import actor_headers
from tests.postgresql_support import mvp_database
from tests.test_web_auth_postgresql import actors
from tests.test_web_session_http import client


def test_resume_partial_profile_and_ignore_duplicate_answers(mvp_database, actors, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "onboarding-test-bot")
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_ENABLED", True)
    monkeypatch.setattr(workflow, "sessions", mvp_database)

    async def database():
        async with mvp_database() as db:
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_session, database)
    owner, stranger = actors

    async def run():
        async with mvp_database.begin() as db:
            user = await db.scalar(select(User).where(User.telegram_id == owner))
            user.first_name = "Telegram name"
            db.add(BrandProfile(user_id=user.id, product_description="Retained product", goals=["Retained goal"]))
        try:
            async with client() as bot:
                headers = actor_headers(owner)
                base = "/workflows/onboarding"
                assert (await bot.get(base, headers=headers)).json() == {"step": "name"}
                result = await bot.put(base + "/name", headers=headers, json={"name": "Chosen name"})
                assert result.json() == {"step": "audience"}
            # A fresh transport and transaction recover the same step from PostgreSQL.
            async with client() as bot:
                assert (await bot.get(base, headers=headers)).json() == {"step": "audience"}
                assert (await bot.get(base, headers=actor_headers(stranger))).json() == {"step": "name"}
                endpoint = "/workflows/profile?onboarding_step=audience"
                replies = await asyncio.gather(
                    bot.put(endpoint, headers=headers, json={"audience": "Neighbors"}),
                    bot.put(endpoint, headers=headers, json={"audience": "Neighbors"}),
                )
                assert [reply.json() for reply in replies] == [{"step": "ready"}] * 2
                updated = await bot.put(base + "/name", headers=headers, json={"name": "Edited", "replace": True})
                assert updated.json() == {"step": "ready"}
            async with mvp_database() as db:
                assert (await db.get(User, user.id)).first_name == "Telegram name"
                assert (await db.get(UserPreferredName, user.id)).display_name == "Edited"
                profile = await db.scalar(select(BrandProfile).where(BrandProfile.user_id == user.id))
                assert (profile.product_description, profile.audience, profile.goals) == (
                    "Retained product", "Neighbors", ["Retained goal"])
        finally:
            async with mvp_database.begin() as db:
                await db.execute(delete(BrandProfile).where(BrandProfile.user_id == user.id))

    asyncio.run(run())
