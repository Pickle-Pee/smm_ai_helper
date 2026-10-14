"""Drain admission against disposable PostgreSQL; all provider calls are offline."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import importlib
import json
import os
from types import SimpleNamespace
import uuid

import httpx
import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings
from app.models import JobExecution, JobStatus, User
from app.module_execution import ModuleExecutorDispatcher
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.service import GraphExecutionService, evaluate_result
from app.orchestration_runtime.worker import ModuleGraphWorker
from app.services.worker_drain_service import WorkerDrainControl, ControlError
from app.worker import MarketingWorker
from app.workflows.executors import MarketingExecutors
from app.workflows.presentation import delivery_parts
from app.workflows.service import MarketingWorkflowService
from tests.graph_fakes import compiled, registry, FakeModel as GraphModel
from tests.postgresql_support import mvp_database
from tests.test_graph_model_adapter import install_transport
from tests.test_graph_postgresql import Clock, cleanup, state
from tests.test_marketing_mvp_postgresql import request
from tests.workflow_fakes import FakeAnalyzer, FakeImages, FakeModel as FixedModel


@asynccontextmanager
async def lane_run(db, lane, *, model=None, real_provider=False):
    """Each test owns its runs; reset global admission even after a failed assertion."""
    control = WorkerDrainControl(db)
    await control.resume()
    clock = Clock()
    if lane == "graph":
        executors = registry(production_model_call if real_provider else model)
        service = GraphExecutionService(db, executors=executors, clock=clock)
        async with db() as session, session.begin():
            user = User(telegram_id=int(uuid.uuid4().hex[:12], 16))
            session.add(user)
            await session.flush()
            owner = user.id
        rid = uuid.uuid4().hex
        await service.start_compiled_run(owner_id=owner, run_id=rid, plan=compiled(executors))
        worker = ModuleGraphWorker(service)
        replacement = lambda: GraphExecutionService(db, executors=registry(), clock=clock)
    else:
        service = MarketingWorkflowService(db, clock=clock)
        actor = int(uuid.uuid4().hex[:12], 16)
        saved = await service.start(actor, request())
        rid = saved["run_id"]
        async with db() as session:
            owner = await session.scalar(select(User.id).where(User.telegram_id == actor))
        options = {} if real_provider else {"model_call": model or FixedModel()}
        executors = MarketingExecutors(analyzer=FakeAnalyzer(), images=FakeImages(), **options)
        worker = MarketingWorker(service, executors)
        replacement = lambda: MarketingWorkflowService(db, clock=clock)
    job_id = (await state(db, rid))[1][0].job_id
    try:
        yield SimpleNamespace(service=service, worker=worker, control=control, clock=clock,
                              rid=rid, owner=owner, job_id=job_id, replacement=replacement,
                              executors=executors, lane=lane)
    finally:
        await cleanup(db, rid, owner)
        await control.resume()


async def finish(ctx, item):
    if ctx.lane == "fixed":
        artifact = await ctx.executors.execute(item)
        return await ctx.service.finish(item, artifact, delivery_parts(artifact))
    binding, request = await ctx.service.load_work(item)
    result = await ModuleExecutorDispatcher(ctx.executors).dispatch(binding, request)
    return await ctx.service.finish(item, result, evaluate_result(item.job_id, result, request.upstream_results))


async def wait_for_database_lock(db, application_name):
    """Observe the actual PostgreSQL lock waiter instead of relying on race timing."""
    async with asyncio.timeout(10):
        while True:
            async with db() as session:
                blocked = await session.scalar(text(
                    "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                    "WHERE application_name = :name AND wait_event_type = 'Lock')"
                ), {"name": application_name})
            if blocked:
                return
            await asyncio.sleep(.01)


@pytest.mark.parametrize("lane", ["fixed", "graph"])
def test_pause_serializes_with_in_progress_claim_transaction(mvp_database, monkeypatch, lane):
    async def exercise():
        async with lane_run(mvp_database, lane) as ctx:
            module = importlib.import_module(
                "app.workflows.service" if lane == "fixed" else "app.orchestration_runtime.service")
            original = module.claim_admitted
            admitted, release = asyncio.Event(), asyncio.Event()

            async def hold_admitted_claim(session):
                result = await original(session)
                if result:
                    admitted.set()
                    await release.wait()  # Admission lock still belongs to the real claim transaction.
                return result

            monkeypatch.setattr(module, "claim_admitted", hold_admitted_claim)
            name = "drain-pause-" + uuid.uuid4().hex
            engine = create_async_engine(os.environ["MVP_TEST_DATABASE_URL"], poolclass=NullPool,
                connect_args={"server_settings": {"application_name": name}})
            operator = WorkerDrainControl(async_sessionmaker(engine, expire_on_commit=False))
            claimant = asyncio.create_task(ctx.service.claim(ctx.job_id))
            pausing = None
            try:
                await asyncio.wait_for(admitted.wait(), 10)
                pausing = asyncio.create_task(operator.pause())
                await wait_for_database_lock(mvp_database, name)
                assert not pausing.done()  # pause cannot confirm ahead of a committed claim.
                release.set()
                item = await asyncio.wait_for(claimant, 10)
                paused = await asyncio.wait_for(pausing, 10)
                assert item is not None and paused["admission"] == "paused"
                # Independent worker service instances cannot bypass the committed pause.
                assert await asyncio.gather(*(ctx.replacement().claim(ctx.job_id) for _ in range(6))) == [None] * 6
                assert await ctx.service.claim() is None  # Authoritative due scan is also closed.
                status = await ctx.control.status(expected_epoch=paused["epoch"])
                assert status["lanes"][lane]["outstanding_attempts"] == 1
                assert status["lanes"][lane]["active_leases"] == 1
                assert not status["drained"]
                assert await finish(ctx, item)  # Completion remains admitted while claims are closed.
                drained = await ctx.control.status(expected_epoch=paused["epoch"], require_drained=True)
                assert drained["drained"]
                assert len((await state(mvp_database, ctx.rid))[2]) == 1
            finally:
                release.set()
                for task in (claimant, pausing):
                    if task is not None and not task.done():
                        task.cancel()
                await asyncio.gather(*(t for t in (claimant, pausing) if t is not None), return_exceptions=True)
                await engine.dispose()
    asyncio.run(exercise())


@pytest.mark.parametrize("lane", ["fixed", "graph"])
def test_claim_waits_for_pause_commit_and_never_admits_after_it(mvp_database, monkeypatch, lane):
    async def exercise():
        async with lane_run(mvp_database, lane) as ctx:
            locked, release = asyncio.Event(), asyncio.Event()
            original = ctx.control._snapshot

            async def hold_pause_commit(session, row):
                locked.set()
                await release.wait()  # UPDATE lock is held; paused state is not committed yet.
                return await original(session, row)

            monkeypatch.setattr(ctx.control, "_snapshot", hold_pause_commit)
            name = "drain-claim-" + uuid.uuid4().hex
            engine = create_async_engine(os.environ["MVP_TEST_DATABASE_URL"], poolclass=NullPool,
                connect_args={"server_settings": {"application_name": name}})
            worker = ctx.replacement()
            worker.sessions = async_sessionmaker(engine, expire_on_commit=False)
            pausing = asyncio.create_task(ctx.control.pause())
            claimant = None
            try:
                await asyncio.wait_for(locked.wait(), 10)
                claimant = asyncio.create_task(worker.claim(ctx.job_id))
                await wait_for_database_lock(mvp_database, name)
                assert not claimant.done()
                release.set()
                paused = await asyncio.wait_for(pausing, 10)
                assert await asyncio.wait_for(claimant, 10) is None
                assert paused["admission"] == "paused" and paused["drained"]
                async with mvp_database() as session:
                    execution = await session.get(JobExecution, ctx.job_id)
                    assert execution.attempts == 0 and execution.claim_token is None
            finally:
                release.set()
                for task in (pausing, claimant):
                    if task is not None and not task.done():
                        task.cancel()
                await asyncio.gather(*(t for t in (pausing, claimant) if t is not None), return_exceptions=True)
                await engine.dispose()
    asyncio.run(exercise())


def test_one_pause_covers_both_active_lanes_and_new_producer_jobs(mvp_database, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "IMAGE_STORAGE_PATH", str(tmp_path))
    async def exercise():
        async with lane_run(mvp_database, "fixed") as fixed, lane_run(mvp_database, "graph") as graph:
            fixed_item, graph_item = await asyncio.gather(
                fixed.service.claim(fixed.job_id), graph.service.claim(graph.job_id))
            paused = await fixed.control.pause()
            status = await graph.control.status(expected_epoch=paused["epoch"])
            assert set(status["lanes"]) == {"fixed", "graph"}
            assert all(lane["outstanding_attempts"] == lane["active_leases"] == 1
                       for lane in status["lanes"].values())
            assert await finish(fixed, fixed_item)
            assert not (await fixed.control.status())["drained"]  # Graph remains active.
            # An API/Telegram continuation and graph completion can persist downstream jobs.
            async with mvp_database() as session:
                actor = await session.scalar(select(User.telegram_id).where(User.id == fixed.owner))
            await fixed.service.continue_run(actor, fixed.rid, "creative")
            assert await finish(graph, graph_item)
            status = await fixed.control.status(expected_epoch=paused["epoch"], require_drained=True)
            assert status["drained"]
            assert all(lane["pending_jobs"] == 1 and lane["outstanding_attempts"] == 0
                       for lane in status["lanes"].values())
            assert await asyncio.gather(fixed.service.claim(), graph.service.claim()) == [None, None]
            await fixed.control.resume(expected_epoch=paused["epoch"])
            assert all(await asyncio.gather(fixed.worker.once(), graph.worker.once()))
            assert len((await state(mvp_database, fixed.rid))[2]) == 2
            assert len((await state(mvp_database, graph.rid))[2]) == 2
    asyncio.run(exercise())


@pytest.mark.parametrize("lane", ["fixed", "graph"])
def test_pause_before_claim_survives_restart_and_pending_jobs_resume_once(mvp_database, lane):
    async def exercise():
        async with lane_run(mvp_database, lane) as ctx:
            paused = await ctx.control.pause()
            restarted_control = WorkerDrainControl(mvp_database)
            assert (await restarted_control.status())["epoch"] == paused["epoch"]
            assert await asyncio.gather(*(ctx.replacement().claim(ctx.job_id) for _ in range(6))) == [None] * 6
            drained = await restarted_control.status(expected_epoch=paused["epoch"], require_drained=True)
            assert drained["drained"] and drained["lanes"][lane]["pending_jobs"] == 1
            async with mvp_database() as session:
                execution = await session.get(JobExecution, ctx.job_id)
                assert execution.attempts == 0 and execution.claim_token is None
            resumed = await restarted_control.resume(expected_epoch=paused["epoch"])
            assert resumed["admission"] == "open" and resumed["epoch"] > paused["epoch"]
            claims = await asyncio.gather(*(ctx.replacement().claim(ctx.job_id) for _ in range(6)))
            assert sum(c is not None for c in claims) == 1
            assert await finish(ctx, next(c for c in claims if c))
            assert not await ctx.worker.once(ctx.job_id)
            _, jobs, artifacts = await state(mvp_database, ctx.rid)
            assert next(j for j in jobs if j.job_id == ctx.job_id).status is JobStatus.SUCCEEDED
            assert len(artifacts) == 1
    asyncio.run(exercise())


@pytest.mark.parametrize("lane", ["fixed", "graph"])
def test_in_flight_openai_transport_finishes_without_transaction_or_cancellation(mvp_database, monkeypatch, lane):
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        calls, cancelled = [], []
        graph_model, fixed_model = GraphModel(use_parents=True), FixedModel()

        async def respond(request):
            payload = json.loads(request.content)
            calls.append(payload)
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
            fmt = payload["text"]["format"]
            if lane == "graph":
                answer = await graph_model(instruction=payload["input"][0]["content"],
                    text=payload["input"][1]["content"], response_schema=fmt["schema"])
            else:
                answer, _ = await fixed_model(messages=payload["input"], response_format=fmt)
            return httpx.Response(200, json={"status": "completed", "output_text": answer})

        clients = install_transport(monkeypatch, respond)
        async with lane_run(mvp_database, lane, real_provider=True) as ctx:
            attempt = asyncio.create_task(ctx.worker.once(ctx.job_id))
            try:
                await asyncio.wait_for(entered.wait(), 10)
                # pause completes while the provider is held: claim transaction is already released.
                paused = await asyncio.wait_for(ctx.control.pause(), 5)
                status = await ctx.control.status(expected_epoch=paused["epoch"])
                assert status["lanes"][lane]["outstanding_attempts"] == 1
                assert not status["drained"] and not attempt.done()
                assert await ctx.replacement().claim() is None
                with pytest.raises(ControlError):
                    await ctx.control.status(expected_epoch=paused["epoch"], require_drained=True)
                release.set()
                assert await asyncio.wait_for(attempt, 10)
                assert not cancelled and len(calls) == 1
                assert (await ctx.control.status(expected_epoch=paused["epoch"], require_drained=True))["drained"]
                assert len((await state(mvp_database, ctx.rid))[2]) == 1
                await ctx.control.resume(expected_epoch=paused["epoch"])
                assert not await ctx.worker.once(ctx.job_id)
                assert len(calls) == len((await state(mvp_database, ctx.rid))[2]) == 1
                assert all(client.is_closed for client in clients)
            finally:
                release.set()
                if not attempt.done():
                    attempt.cancel()
                await asyncio.gather(attempt, return_exceptions=True)
    asyncio.run(exercise())


@pytest.mark.parametrize("lane", ["fixed", "graph"])
def test_retry_deferral_counts_as_drained_and_retains_retry_owner(mvp_database, lane):
    async def exercise():
        async with lane_run(mvp_database, lane) as ctx:
            item = await ctx.service.claim(ctx.job_id)
            paused = await ctx.control.pause()
            if lane == "fixed":
                assert await ctx.service.fail(item, retryable=True, message="offline retry")
            else:
                assert await ctx.service.fail(item, retryable=True, code="provider_transient")
            status = await ctx.control.status(expected_epoch=paused["epoch"], require_drained=True)
            assert status["drained"]
            assert status["lanes"][lane]["outstanding_attempts"] == 0
            assert status["lanes"][lane]["active_leases"] == 0
            assert status["lanes"][lane]["deferred_jobs"] == 1
            async with mvp_database() as session:
                execution = await session.get(JobExecution, ctx.job_id)
                due_at = execution.available_at
                assert execution.attempts == 1 and execution.claim_token is None
            assert due_at == ctx.clock() + timedelta(seconds=5)
            assert await ctx.replacement().claim(ctx.job_id) is None
            await ctx.control.resume(expected_epoch=paused["epoch"])
            assert await ctx.replacement().claim(ctx.job_id) is None  # Pause does not erase backoff.
            ctx.clock.tick(6)
            claims = await asyncio.gather(*(ctx.replacement().claim(ctx.job_id) for _ in range(4)))
            assert sum(c is not None for c in claims) == 1
            assert await finish(ctx, next(c for c in claims if c))
            async with mvp_database() as session:
                assert (await session.get(JobExecution, ctx.job_id)).attempts == 2
            assert len((await state(mvp_database, ctx.rid))[2]) == 1
    asyncio.run(exercise())


@pytest.mark.parametrize("lane", ["fixed", "graph"])
def test_expired_claim_token_is_not_false_drain_evidence(mvp_database, lane):
    async def exercise():
        async with lane_run(mvp_database, lane) as ctx:
            item = await ctx.service.claim(ctx.job_id)
            async with mvp_database() as session, session.begin():
                await session.execute(update(JobExecution).where(JobExecution.job_id == ctx.job_id)
                    .values(lease_until=datetime.now(timezone.utc) - timedelta(seconds=1)))
            paused = await ctx.control.pause()
            status = await ctx.control.status(expected_epoch=paused["epoch"])
            assert status["lanes"][lane]["active_leases"] == 0
            assert status["lanes"][lane]["outstanding_attempts"] == 1
            assert not status["drained"]
            with pytest.raises(ControlError):
                await ctx.control.status(expected_epoch=paused["epoch"], require_drained=True)
            safe = json.dumps(status)
            assert item.job_id not in safe
            assert getattr(item, "token", getattr(item, "claim_token", "")) not in safe
            assert await ctx.replacement().claim(ctx.job_id) is None
    asyncio.run(exercise())


@pytest.mark.parametrize("lane", ["fixed", "graph"])
def test_database_outage_never_reopens_admission_or_issues_claim(mvp_database, lane):
    async def exercise():
        async with lane_run(mvp_database, lane) as ctx:
            paused = await ctx.control.pause()
            url = mvp_database.kw["bind"].url.set(port=1)
            engine = create_async_engine(url, poolclass=NullPool, connect_args={"timeout": .2})
            unavailable = async_sessionmaker(engine, expire_on_commit=False)
            service = ctx.replacement()
            service.sessions = unavailable
            broken_control = WorkerDrainControl(unavailable)
            try:
                with pytest.raises((OSError, SQLAlchemyError)):
                    await service.claim(ctx.job_id)
                for operation in (broken_control.pause, broken_control.resume, broken_control.status):
                    with pytest.raises((OSError, SQLAlchemyError)):
                        await operation()
                restored = await WorkerDrainControl(mvp_database).status(expected_epoch=paused["epoch"])
                assert restored["admission"] == "paused" and restored["drained"]
                async with mvp_database() as session:
                    assert (await session.get(JobExecution, ctx.job_id)).attempts == 0
                assert not await ctx.worker.once(ctx.job_id)
                assert not (await state(mvp_database, ctx.rid))[2]
            finally:
                await engine.dispose()
    asyncio.run(exercise())


@pytest.mark.parametrize("lane", ["fixed", "graph"])
def test_superseded_attempt_in_provider_io_still_prevents_drain(mvp_database, lane):
    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        provider = FixedModel() if lane == "fixed" else GraphModel(use_parents=True)

        async def held_provider(**kwargs):
            entered.set()
            await release.wait()
            return await provider(**kwargs)

        async with lane_run(mvp_database, lane, model=held_provider) as ctx:
            original = asyncio.create_task(ctx.worker.once(ctx.job_id))
            try:
                await asyncio.wait_for(entered.wait(), 10)
                # Wall-clock lease expiry does not mean the original monotonic provider
                # timeout has elapsed. A replacement can finish while the original is held.
                ctx.clock.tick(400)
                replacement_service = ctx.replacement()
                if lane == "graph":
                    replacement = ModuleGraphWorker(replacement_service)
                else:
                    replacement = MarketingWorker(replacement_service, MarketingExecutors(
                        model_call=FixedModel(), analyzer=FakeAnalyzer(), images=FakeImages()))
                assert await replacement.once(ctx.job_id)
                async with mvp_database() as session:
                    execution = await session.get(JobExecution, ctx.job_id)
                    assert execution.attempts == 2 and execution.claim_token is None
                assert len((await state(mvp_database, ctx.rid))[2]) == 1
                assert not original.done()
                paused = await ctx.control.pause()
                status = await ctx.control.status(expected_epoch=paused["epoch"])
                assert status["lanes"][lane]["active_leases"] == 0
                assert status["lanes"][lane]["outstanding_attempts"] == 1
                assert not status["drained"]
                with pytest.raises(ControlError):
                    await ctx.control.status(expected_epoch=paused["epoch"], require_drained=True)
                release.set()
                assert await asyncio.wait_for(original, 10)
                drained = await ctx.control.status(expected_epoch=paused["epoch"], require_drained=True)
                assert drained["drained"] and drained["lanes"][lane]["outstanding_attempts"] == 0
                assert len(provider.calls) == 1
                assert len((await state(mvp_database, ctx.rid))[2]) == 1  # Stale result remains fenced.
            finally:
                release.set()
                if not original.done():
                    original.cancel()
                await asyncio.gather(original, return_exceptions=True)
    asyncio.run(exercise())


@pytest.mark.parametrize("lane", ["fixed", "graph"])
def test_attempt_release_cannot_clear_another_workers_marker(mvp_database, lane):
    from app.models import WorkerAttempt

    async def exercise():
        async with lane_run(mvp_database, lane) as ctx:
            first = await ctx.service.claim(ctx.job_id)
            ctx.clock.tick(400)
            other = ctx.replacement()
            second = await other.claim(ctx.job_id)
            first_token = getattr(first, "token", getattr(first, "claim_token", None))
            second_token = getattr(second, "token", getattr(second, "claim_token", None))
            assert first_token != second_token
            await ctx.service.release_attempt(first)
            async with mvp_database() as session:
                markers = (await session.scalars(select(WorkerAttempt).where(
                    WorkerAttempt.job_id == ctx.job_id))).all()
                assert [marker.claim_token for marker in markers] == [second_token]
            paused = await ctx.control.pause()
            status = await ctx.control.status(expected_epoch=paused["epoch"])
            # The current claim and its marker represent one attempt, not two.
            assert status["lanes"][lane]["outstanding_attempts"] == 1
            assert not status["drained"]
            assert await finish(ctx, second)
            assert (await ctx.control.status(expected_epoch=paused["epoch"], require_drained=True))["drained"]
    asyncio.run(exercise())
