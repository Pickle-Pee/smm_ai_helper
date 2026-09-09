"""Short PostgreSQL transactions for standalone continuation ownership.

Claims cover routing as well as final generation because routing itself is external.
No worker/Redis dependency, lease renewal, or automatic provider retry is introduced.
"""
from datetime import timedelta
import uuid

from sqlalchemy import func, select, update

from app.models import TaskSessionRecord
from app.services.task_session_service import TaskSessionService


class TaskFinalizationUnavailable(RuntimeError):
    """Retry the same session later; it has no new canonical completion yet."""


class TaskFinalizationService:
    @staticmethod
    async def locked_record(session, session_id):
        record = await session.scalar(
            select(TaskSessionRecord)
            .where(TaskSessionRecord.session_id == session_id)
            .with_for_update().execution_options(populate_existing=True)
        )
        if record is None:
            raise ValueError("Unknown session")
        return record

    @classmethod
    async def acquire(cls, session, session_id, lease_seconds, answer=None):
        """Return a detached claim/replay snapshot, or None while another owner works.

        Only the winner changes answers. PostgreSQL's clock is sampled after locking;
        callers with stale ORM identity maps cannot overwrite the winning snapshot.
        """
        try:
            record = await cls.locked_record(session, session_id)
            now = await session.scalar(select(func.clock_timestamp()))
            if record.completed_response is not None:
                state = TaskSessionService._to_state(record)
            elif record.finalization_token and record.finalization_lease_until > now:
                state = None
            else:
                record.finalization_token = uuid.uuid4().hex
                record.finalization_lease_until = now + timedelta(seconds=lease_seconds)
                if answer is not None:
                    record.answers = {**(record.answers or {}), answer[0]: answer[1]}
                state = TaskSessionService._to_state(record)
            await session.commit()
            return state
        except BaseException:
            await session.rollback()
            raise

    @staticmethod
    async def require_owner(session, record, state):
        """Validate a locked record before writes; caller owns commit/rollback."""
        now = await session.scalar(select(func.clock_timestamp()))
        if (not state.finalization_token or record.finalization_token != state.finalization_token
                or record.finalization_lease_until is None or record.finalization_lease_until <= now):
            raise TaskFinalizationUnavailable("Task execution ownership expired; retry this session")

    @classmethod
    async def check_owned(cls, session, state):
        """Fence each external stage, releasing the transaction before calling out."""
        try:
            record = await cls.locked_record(session, state.session_id)
            await cls.require_owner(session, record, state)
            await session.commit()
        except BaseException:
            await session.rollback()
            raise

    @classmethod
    async def finish_clarification(cls, session, state):
        try:
            record = await cls.locked_record(session, state.session_id)
            await cls.require_owner(session, record, state)
            record.questions_asked = state.questions_asked
            record.finalization_token = record.finalization_lease_until = None
            await session.commit()
        except BaseException:
            await session.rollback()
            raise

    @staticmethod
    async def release(session, state):
        """Failure cleanup cannot clear a successor's claim, even after lease expiry."""
        try:
            await session.execute(
                update(TaskSessionRecord).where(
                    TaskSessionRecord.session_id == state.session_id,
                    TaskSessionRecord.finalization_token == state.finalization_token,
                ).values(finalization_token=None, finalization_lease_until=None)
                .execution_options(synchronize_session=False)
            )
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
