from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TaskSessionRecord


@dataclass
class TaskSessionState:
    session_id: str
    agent_type: str
    task_description: str
    mode: str
    answers: Dict[str, Any] = field(default_factory=dict)
    questions_asked: int = 0
    request_id: str = "-"
    user_id: str = "anonymous"


class TaskSessionService:
    """Persistent storage for multi-step task sessions."""

    @staticmethod
    def _to_state(record: TaskSessionRecord) -> TaskSessionState:
        return TaskSessionState(
            session_id=record.session_id,
            agent_type=record.agent_type,
            task_description=record.task_description,
            mode=record.mode,
            answers=record.answers or {},
            questions_asked=record.questions_asked or 0,
            request_id=record.request_id or "-",
            user_id=record.user_id or "anonymous",
        )

    @classmethod
    async def get(
        cls,
        db_session: AsyncSession,
        session_id: str,
    ) -> TaskSessionState | None:
        record = await db_session.get(TaskSessionRecord, session_id)
        if not record:
            return None
        return cls._to_state(record)

    @classmethod
    async def save(
        cls,
        db_session: AsyncSession,
        state: TaskSessionState,
    ) -> TaskSessionState:
        record = await db_session.get(TaskSessionRecord, state.session_id)
        if not record:
            record = TaskSessionRecord(session_id=state.session_id)
            db_session.add(record)

        record.agent_type = state.agent_type
        record.task_description = state.task_description
        record.mode = state.mode
        record.answers = state.answers or {}
        record.questions_asked = state.questions_asked
        record.request_id = state.request_id
        record.user_id = state.user_id
        record.updated_at = datetime.utcnow()

        await db_session.flush()
        return state

    @staticmethod
    async def delete(
        db_session: AsyncSession,
        session_id: str,
    ) -> None:
        record = await db_session.get(TaskSessionRecord, session_id)
        if record:
            await db_session.delete(record)
            await db_session.flush()
