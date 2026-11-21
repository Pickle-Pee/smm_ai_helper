import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.config import settings
from app.models import BrandProfile, User
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
