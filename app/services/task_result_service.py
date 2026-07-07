from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task


class TaskResultService:
    """Persists completed task results to task history."""

    @staticmethod
    async def save_done_task(
        db_session: AsyncSession,
        user_id: int | None,
        agent_type: str,
        task_description: str,
        answers: Dict[str, Any] | None,
        result: Dict[str, Any],
    ) -> Task:
        task = Task(
            user_id=user_id,
            agent_type=agent_type,
            task_description=task_description,
            answers=answers,
            result=result,
            status="done",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        return task
