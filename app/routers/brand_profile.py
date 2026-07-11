from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import BrandProfileRead, BrandProfileUpdate
from app.services.brand_profile_service import BrandProfileService
from app.services.user_service import UserService


router = APIRouter(prefix="/brand-profile", tags=["brand-profile"])


@router.get("/{telegram_id}", response_model=BrandProfileRead)
async def get_brand_profile(
    telegram_id: int,
    session: AsyncSession = Depends(get_session),
):
    profile = await BrandProfileService.get_by_telegram_id(session, telegram_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Brand profile not found")
    return profile


@router.patch("/{telegram_id}", response_model=BrandProfileRead)
async def patch_brand_profile(
    telegram_id: int,
    payload: BrandProfileUpdate,
    session: AsyncSession = Depends(get_session),
):
    user = await UserService.get_by_telegram_id(session, telegram_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        return await BrandProfileService.upsert_for_user(
            session=session,
            user_id=user.id,
            values=values,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
