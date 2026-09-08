"""Atomically store standalone history and the replayable session outcome."""
from sqlalchemy import select

from app.models import Task, TaskSessionRecord
from app.services.user_service import UserService


class TaskCompletionService:
    @staticmethod
    async def complete(session, state, response):
        try:
            record = await session.scalar(
                select(TaskSessionRecord)
                .where(TaskSessionRecord.session_id == state.session_id)
                .with_for_update().execution_options(populate_existing=True)
            )
            if record is None:
                raise ValueError("Unknown session")
            if record.completed_response is not None:
                saved = record.completed_response
                await session.commit()
                return saved
            user = None
            if state.user_id != "anonymous":
                user = await UserService.get_by_telegram_id(session, int(state.user_id))
                if user is None:
                    raise ValueError("Task owner no longer exists")
            session.add(Task(
                user_id=user.id if user else None, agent_type=state.agent_type,
                task_description=state.task_description, answers=dict(state.answers),
                result=response["result"], status="done",
            ))
            record.completed_response = response
            await session.commit()
            return response
        except Exception:
            await session.rollback()
            raise
