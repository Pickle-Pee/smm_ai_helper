"""Telegram generation admission at the bot-authenticated HTTP boundary."""
from fastapi import Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.security import require_actor
from app.services.brand_profile_service import BrandProfileService
from app.services.identity_service import IdentityService
from app.services.telegram_onboarding import missing_brand_steps


def onboarding_enabled(actor: int) -> bool:
    cohort = settings.TELEGRAM_ONBOARDING_COHORT
    return settings.TELEGRAM_ONBOARDING_ENABLED and (not cohort or actor in cohort)


async def require_ready_profile(
    actor: int = Depends(require_actor),
    db: AsyncSession = Depends(get_session),
) -> None:
    if not onboarding_enabled(actor):
        return
    try:
        owner = await IdentityService.resolve_telegram_user_id(db, actor)
        profile = await BrandProfileService.get_by_user_id(db, owner) if owner is not None else None
        missing = missing_brand_steps(profile)
        await db.rollback()
    except (SQLAlchemyError, OSError):
        raise HTTPException(503, "temporarily_unavailable") from None
    if missing:
        raise HTTPException(409, "onboarding_required")
