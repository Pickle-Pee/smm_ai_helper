from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.schemas import UserCreate


class UserService:
    """User-related database operations shared across API flows."""

    @staticmethod
    async def get_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_or_create(
        cls,
        session: AsyncSession,
        user_data: UserCreate | None,
    ) -> User | None:
        if user_data is None:
            return None

        user = await cls.get_by_telegram_id(session, user_data.telegram_id)
        if user:
            return user

        user = User(
            telegram_id=user_data.telegram_id,
            username=user_data.username,
            first_name=user_data.first_name,
            last_name=user_data.last_name,
        )
        session.add(user)
        await session.flush()
        await session.refresh(user)
        return user
