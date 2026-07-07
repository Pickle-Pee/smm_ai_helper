from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.services.user_service import UserService


class TaskHistoryService:
    """Reads task history and individual task records."""

    @staticmethod
    async def get_task(
        db_session: AsyncSession,
        task_id: int,
    ) -> Task | None:
        result = await db_session.execute(
            select(Task).where(Task.id == task_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_recent_tasks_by_telegram_id(
        db_session: AsyncSession,
        telegram_id: int,
        limit: int,
    ) -> list[Task]:
        user = await UserService.get_by_telegram_id(db_session, telegram_id)
        if not user:
            return []

        result = await db_session.execute(
            select(Task)
            .where(Task.user_id == user.id)
            .order_by(desc(Task.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())
