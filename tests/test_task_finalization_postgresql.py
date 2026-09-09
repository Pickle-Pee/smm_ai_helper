"""Exercise real standalone answer orchestration with PostgreSQL and provider doubles."""
import asyncio
from collections import Counter
import os
import subprocess
import sys

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import Task, TaskSessionRecord
from app.services.task_completion_service import TaskCompletionService
from app.services.task_finalization_service import TaskFinalizationService, TaskFinalizationUnavailable
from app.services.task_pipeline import TaskPipelineService
from tests.postgresql_support import mvp_database
from tests.test_task_completion_postgresql import seed


def pipeline_with_doubles(session, sessions, state, counts, agent_hook=None, clarify=False):
    pipeline = TaskPipelineService()

    async def external(stage):
        assert not session.in_transaction(), f"transaction held during {stage}"
        # A second connection can immediately lock the row while the provider runs.
        async with sessions() as observer:
            row = await observer.scalar(select(TaskSessionRecord).where(
                TaskSessionRecord.session_id == state.session_id,
            ).with_for_update(nowait=True))
            assert row.finalization_token is not None
            await observer.commit()
        counts[stage] += 1

    async def route(*_args):
        await external("router")
        return {"needs_clarification": clarify, "needs_qc": True,
                "model": "fake-model", "max_output_tokens": 100}, {}

    async def agent(**_kwargs):
        await external("agent")
        if agent_hook:
            await agent_hook()
        return {"content": "canonical", "confidence": "high", "warnings": []}

    async def qc(*_args):
        await external("qc")
        return []

    async def image(*_args):
        await external("image")
        return {"url": "/images/fake.png"}

    async def questions(*_args):
        await external("clarification")
        return [{"key": "audience", "question": "Who is the audience?"}]

    pipeline.task_router.route = route
    pipeline.agent_runner.run = agent
    pipeline.qc_service.find_issues = qc
    pipeline.task_image_service.generate_for_task_session = image
    pipeline.clarification_service.generate_questions = questions
    return pipeline


async def assert_canonical(sessions, owner, state, response):
    async with sessions() as session:
        record = await session.get(TaskSessionRecord, state.session_id)
        assert record.completed_response == response
        assert record.finalization_token is record.finalization_lease_until is None
        rows = (await session.scalars(select(Task).where(Task.user_id == owner))).all()
        assert len(rows) == 1
        assert rows[0].result == response["result"]
        assert rows[0].answers == record.answers
        return record.answers


def test_concurrent_real_answers_execute_once_and_replay_canonical(mvp_database, monkeypatch):
    async def run():
        owner, state = await seed(mvp_database)
        entered, release, contender_waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
        counts = Counter()
        acquire = TaskFinalizationService.acquire

        async def observed_acquire(*args, **kwargs):
            result = await acquire(*args, **kwargs)
            if result is None:
                assert not args[0].in_transaction()
                contender_waiting.set()
            return result

        monkeypatch.setattr(TaskFinalizationService, "acquire", observed_acquire)

        async def hold_agent():
            entered.set()
            await release.wait()

        async with mvp_database() as first_db, mvp_database() as second_db:
            # Keep a stale identity-mapped row, as HTTP authorization can do.
            stale_record = await second_db.get(TaskSessionRecord, state.session_id)
            first_pipeline = pipeline_with_doubles(first_db, mvp_database, state, counts, hold_agent)
            second_pipeline = pipeline_with_doubles(second_db, mvp_database, state, counts)
            async with asyncio.timeout(10):
                first = asyncio.create_task(first_pipeline.answer(first_db, state.session_id, "goal", "winner"))
                await entered.wait()
                second = asyncio.create_task(second_pipeline.answer(second_db, state.session_id, "goal", "contender"))
                try:
                    await contender_waiting.wait()  # Force the actual pre-completion race.
                    assert counts == {"router": 1, "agent": 1}
                    assert stale_record.answers == {"goal": "winner"}
                finally:
                    release.set()
                a, b = await asyncio.gather(first, second)
            assert a == b
            assert not first_db.in_transaction() and not second_db.in_transaction()
        assert counts == {"router": 1, "agent": 1, "qc": 1, "image": 1}
        assert await assert_canonical(mvp_database, owner, state, a) == {"goal": "winner"}
        async with mvp_database() as db:
            replay = pipeline_with_doubles(db, mvp_database, state, counts)
            assert await replay.answer(db, state.session_id, "goal", "later replay") == a
            assert not db.in_transaction()
        assert counts == {"router": 1, "agent": 1, "qc": 1, "image": 1}
        await assert_canonical(mvp_database, owner, state, a)
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["provider", "cancel", "timeout", "commit"])
def test_failed_owner_releases_claim_and_later_answer_completes(mvp_database, monkeypatch, failure):
    async def run():
        owner, state = await seed(mvp_database)
        counts, entered = Counter(), asyncio.Event()

        async def interrupt():
            entered.set()
            if failure == "provider":
                raise RuntimeError("injected provider failure")
            if failure in {"cancel", "timeout"}:
                await asyncio.Event().wait()

        if failure == "timeout":
            monkeypatch.setattr(settings, "TASK_FINALIZATION_TIMEOUT_SECONDS", 0.2)
        async with mvp_database() as db:
            pipeline = pipeline_with_doubles(db, mvp_database, state, counts, interrupt)
            if failure == "commit":
                def fail_completion(session):
                    if any(isinstance(row, Task) for row in session.new):
                        raise RuntimeError("injected commit failure")
                event.listen(db.sync_session, "before_commit", fail_completion)
            task = asyncio.create_task(pipeline.answer(db, state.session_id, "goal", "first"))
            async with asyncio.timeout(5):
                if failure == "cancel":
                    await entered.wait()
                    task.cancel()
                expected = (asyncio.CancelledError if failure == "cancel" else
                            TaskFinalizationUnavailable if failure == "timeout" else RuntimeError)
                with pytest.raises(expected):
                    await task
            assert not db.in_transaction()
        async with mvp_database() as db:
            record = await db.get(TaskSessionRecord, state.session_id)
            assert record.completed_response is record.finalization_token is record.finalization_lease_until is None
            assert await db.scalar(select(func.count()).select_from(Task).where(Task.user_id == owner)) == 0
        monkeypatch.setattr(settings, "TASK_FINALIZATION_TIMEOUT_SECONDS", 240)
        async with mvp_database() as db:
            pipeline = pipeline_with_doubles(db, mvp_database, state, counts)
            response = await pipeline.answer(db, state.session_id, "goal", "retry")
        assert counts["agent"] == 2  # Explicit recovery, not concurrent duplicate generation.
        await assert_canonical(mvp_database, owner, state, response)
    asyncio.run(run())


def test_process_death_leaves_durable_claim_then_expired_claim_recovers(mvp_database):
    async def run():
        owner, state = await seed(mvp_database)
        # A distinct backend process commits a real claim and dies without cleanup.
        script = """
import asyncio, os, sys
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.services.task_finalization_service import TaskFinalizationService
async def run():
    engine = create_async_engine(sys.argv[1])
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        state = await TaskFinalizationService.acquire(db, sys.argv[2], 270, ('goal', 'crashed'))
        assert state.finalization_token
        os._exit(23)
asyncio.run(run())
"""
        process = await asyncio.to_thread(subprocess.run,
            [sys.executable, "-c", script, os.environ["MVP_TEST_DATABASE_URL"], state.session_id],
            capture_output=True, text=True, timeout=20)
        assert process.returncode == 23, process.stderr
        async with mvp_database() as db:
            assert await TaskFinalizationService.acquire(db, state.session_id, 270) is None
            # Advance the persisted lease, not a sleep-based concurrency assumption.
            await db.execute(text("UPDATE task_sessions SET finalization_lease_until = clock_timestamp() - interval '1 second' WHERE session_id = :id"), {"id": state.session_id})
            await db.commit()
        counts = Counter()
        async with mvp_database() as db:
            response = await pipeline_with_doubles(db, mvp_database, state, counts).answer(
                db, state.session_id, "goal", "recovered")
        assert counts == {"router": 1, "agent": 1, "qc": 1, "image": 1}
        assert await assert_canonical(mvp_database, owner, state, response) == {"goal": "recovered"}
    asyncio.run(run())


def test_expired_owner_cannot_execute_commit_or_release_successor(mvp_database):
    async def run():
        owner, state = await seed(mvp_database)
        async with mvp_database() as db:
            old = await TaskFinalizationService.acquire(db, state.session_id, 60)
            await db.execute(text("UPDATE task_sessions SET finalization_lease_until = clock_timestamp() - interval '1 second' WHERE session_id = :id"), {"id": state.session_id})
            await db.commit()
            successor = await TaskFinalizationService.acquire(db, state.session_id, 60)
            with pytest.raises(TaskFinalizationUnavailable):
                await TaskFinalizationService.check_owned(db, old)
            response = {"status": "done", "session_id": state.session_id, "result": {"content": "new"}, "image": None}
            with pytest.raises(TaskFinalizationUnavailable):
                await TaskCompletionService.complete(db, old, response)
            await TaskFinalizationService.release(db, old)
            await TaskFinalizationService.check_owned(db, successor)
            await TaskCompletionService.complete(db, successor, response)
        await assert_canonical(mvp_database, owner, state, response)
    asyncio.run(run())


def test_clarification_releases_claim_then_final_answer_preserves_contract(mvp_database):
    async def run():
        owner, state = await seed(mvp_database)
        counts = Counter()
        async with mvp_database() as db:
            pipeline = pipeline_with_doubles(db, mvp_database, state, counts, clarify=True)
            response = await pipeline.answer(db, state.session_id, "goal", "clarify")
            assert response == {"status": "need_info", "session_id": state.session_id,
                                "questions": [{"key": "audience", "question": "Who is the audience?"}]}
            record = await db.get(TaskSessionRecord, state.session_id)
            assert record.finalization_token is None and record.completed_response is None
            assert record.questions_asked == 1
        async with mvp_database() as db:
            pipeline = pipeline_with_doubles(db, mvp_database, state, counts)
            completed = await pipeline.answer(db, state.session_id, "audience", "experts")
        assert await assert_canonical(mvp_database, owner, state, completed) == {"goal": "clarify", "audience": "experts"}
        assert counts == {"router": 2, "clarification": 1, "agent": 1, "qc": 1, "image": 1}
    asyncio.run(run())


@pytest.mark.parametrize("mutation,constraint", [
    ("finalization_token = 'orphan'", "ck_task_session_claim_pair"),
    ("finalization_lease_until = clock_timestamp()", "ck_task_session_claim_pair"),
    ("finalization_token = 'active', finalization_lease_until = clock_timestamp(), completed_response = '{\"status\":\"done\"}'", "ck_task_session_completed_unclaimed"),
])
def test_postgresql_rejects_inconsistent_claim_state(mvp_database, mutation, constraint):
    async def run():
        _, state = await seed(mvp_database)
        async with mvp_database() as db:
            with pytest.raises(IntegrityError, match=constraint):
                await db.execute(text(f"UPDATE task_sessions SET {mutation} WHERE session_id = :id"), {"id": state.session_id})
            await db.rollback()
            record = await db.get(TaskSessionRecord, state.session_id)
            assert record.completed_response is record.finalization_token is record.finalization_lease_until is None
    asyncio.run(run())
