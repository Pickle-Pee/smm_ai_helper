import asyncio
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, func, select

from app.models import Task, TaskSessionRecord, User
from app.services.task_completion_service import TaskCompletionService
from app.services.task_pipeline import TaskPipelineService
from app.services.task_session_service import TaskSessionService, TaskSessionState
from tests.postgresql_support import mvp_database


async def seed(sessions):
    actor = int(uuid.uuid4().hex[:12], 16)
    async with sessions() as session:
        user = User(telegram_id=actor)
        session.add(user)
        await session.flush()
        state = TaskSessionState(uuid.uuid4().hex, "strategy", "A real saved task", "text", user_id=str(actor))
        await TaskSessionService.save(session, state)
        await session.commit()
        return user.id, state


def test_failed_commit_preserves_session_then_replay_avoids_generation(mvp_database):
    async def run():
        owner, state = await seed(mvp_database)
        response = {"status": "done", "session_id": state.session_id, "result": {"content": "saved"}, "image": None}
        async with mvp_database() as session:
            def fail(_session):
                raise RuntimeError("injected persistence failure")
            event.listen(session.sync_session, "before_commit", fail, once=True)
            with pytest.raises(RuntimeError, match="injected"):
                await TaskCompletionService.complete(session, state, response)
        async with mvp_database() as session:
            record = await session.get(TaskSessionRecord, state.session_id)
            assert record.completed_response is None
            assert await session.scalar(select(func.count()).select_from(Task).where(Task.user_id == owner)) == 0
            assert await TaskCompletionService.complete(session, state, response) == response
        async with mvp_database() as session:
            pipeline = TaskPipelineService()
            pipeline._continue_session = AsyncMock(side_effect=AssertionError("must not generate again"))
            assert await pipeline.answer(session, state.session_id, "same", "request") == response
            pipeline._continue_session.assert_not_called()
            assert await session.scalar(select(func.count()).select_from(Task).where(Task.user_id == owner)) == 1
    asyncio.run(run())


def test_competing_completion_returns_one_persisted_outcome(mvp_database):
    async def run():
        owner, state = await seed(mvp_database)
        async def finish(label):
            async with mvp_database() as session:
                return await TaskCompletionService.complete(session, state, {
                    "status": "done", "session_id": state.session_id, "result": {"content": label}, "image": None,
                })
        first, second = await asyncio.gather(finish("one"), finish("two"))
        assert first == second
        async with mvp_database() as session:
            rows = (await session.scalars(select(Task).where(Task.user_id == owner))).all()
            assert len(rows) == 1 and rows[0].result == first["result"]
    asyncio.run(run())
