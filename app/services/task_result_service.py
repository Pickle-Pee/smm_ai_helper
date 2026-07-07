from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.services.task_session_service import TaskSessionState
from app.services.user_service import UserService


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

    @staticmethod
    async def save_error_task(
        db_session: AsyncSession,
        user_id: int | None,
        agent_type: str,
        task_description: str,
        answers: Dict[str, Any] | None,
        error: str,
    ) -> Task:
        task = Task(
            user_id=user_id,
            agent_type=agent_type,
            task_description=task_description,
            answers=answers,
            result=None,
            status="error",
            error=error,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)
        return task

    @classmethod
    async def save_done_task_from_session(
        cls,
        db_session: AsyncSession,
        session_state: TaskSessionState,
        result: Dict[str, Any],
        extra_answers: Dict[str, Any] | None = None,
    ) -> Task:
        answers = dict(session_state.answers or {})
        if extra_answers:
            answers.update(extra_answers)

        user_id = None
        if session_state.user_id != "anonymous":
            user = await UserService.get_by_telegram_id(
                db_session,
                int(session_state.user_id),
            )
            user_id = user.id if user else None

        return await cls.save_done_task(
            db_session=db_session,
            user_id=user_id,
            agent_type=session_state.agent_type,
            task_description=session_state.task_description,
            answers=answers,
            result=result,
        )
