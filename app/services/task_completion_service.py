"""Atomically store standalone history and the replayable session outcome."""
from copy import deepcopy

from app.models import Task
from app.services.task_finalization_service import TaskFinalizationService
from app.services.user_service import UserService


class TaskCompletionService:
    @staticmethod
    async def complete(session, state, response):
        try:
            record = await TaskFinalizationService.locked_record(session, state.session_id)
            if record.completed_response is not None:
                saved = deepcopy(record.completed_response)
                await session.commit()
                return saved
            await TaskFinalizationService.require_owner(session, record, state)
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
            record.finalization_token = record.finalization_lease_until = None
            await session.commit()
            return response
        except BaseException:
            await session.rollback()
            raise
