"""Two production lane families on disposable PostgreSQL/Redis, fake providers."""
import asyncio
from datetime import datetime, timedelta, timezone
from functools import partial
import json
import os
import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import delete, select

from app.models import JobExecution, JobStatus, MarketingRun, User
from app.orchestration_runtime.composition import build_production_graph_runtime
from app.worker import MarketingWorker, main
from app.workflows.executors import MarketingExecutors
from app.workflows.queue import RedisWakeups, FIXED_WAKEUP_KEY, GRAPH_WAKEUP_KEY
from app.workflows.service import MarketingWorkflowService
from tests.postgresql_support import mvp_database
from tests.test_graph_postgresql import Clock, cleanup, state
from tests.test_marketing_mvp_postgresql import request
from tests.test_module_executors import analyzer
from tests.test_strategy_builder import strategy_compiled, strategy_context, StrategyModel
from tests.workflow_fakes import FakeModel, FakeAnalyzer, FakeImages


def fixed_executors(model=None):
    return MarketingExecutors(model_call=model or FakeModel(), analyzer=FakeAnalyzer(), images=FakeImages())


async def seed(db, runtime, fixed_service):
    actor = int(uuid.uuid4().hex[:12], 16)
    fixed = await fixed_service.start(actor, request())
    async with db() as session:
        owner = await session.scalar(select(User.id).where(User.telegram_id == actor))
    rid = uuid.uuid4().hex
    plan = strategy_compiled(strategy_context(("https://competitor.example/",), market=True), runtime.executors)
    await runtime.service.start_compiled_run(owner_id=owner, run_id=rid, plan=plan)
    return actor, owner, fixed, rid


async def cleanup_pair(db, fixed, rid, owner):
    async with db() as session, session.begin():
        await session.execute(delete(MarketingRun).where(MarketingRun.run_id == fixed["run_id"]))
    await cleanup(db, rid, owner)


async def wait_until(check, timeout=20):
    async with asyncio.timeout(timeout):
        while not await check():
            await asyncio.sleep(.05)


@pytest.mark.parametrize("redis_mode", ["available", "lost", "unavailable"])
def test_main_composition_simultaneous_fixed_and_strategy(mvp_database, monkeypatch, redis_mode):
    if not os.getenv("REDIS_TEST_URL"):
        pytest.skip("REDIS_TEST_URL required for isolated production lane integration")
    async def exercise():
        clients, queues = [], []
        model = StrategyModel(use_parents=True)
        original = httpx.AsyncClient
        provider_calls = []
        async def respond(request):
            payload = json.loads(request.content)
            provider_calls.append(payload)
            fmt = payload["text"]["format"]
            assert fmt["strict"] is True and payload["max_output_tokens"] == 4000
            text = await model(instruction=payload["input"][0]["content"], text=payload["input"][1]["content"],
                               response_schema=fmt["schema"])
            return httpx.Response(200, json={"status": "completed", "output_text": text})
        def http_client(**kwargs):
            result = original(**kwargs, transport=httpx.MockTransport(respond))
            clients.append(result)
            return result
        monkeypatch.setattr(httpx, "AsyncClient", http_client)
        def queue_factory(*, key):
            url = "redis://127.0.0.1:1/15" if redis_mode == "unavailable" else os.environ["REDIS_TEST_URL"]
            result = RedisWakeups(Redis.from_url(url, decode_responses=True, socket_connect_timeout=.1,
                                                socket_timeout=2), key=key)
            queues.append(result)
            return result
        fixed_queue, graph_queue = queue_factory(key=FIXED_WAKEUP_KEY), queue_factory(key=GRAPH_WAKEUP_KEY)
        factory = partial(build_production_graph_runtime, analyzer=analyzer())
        runtime = factory(queue=graph_queue, sessions=mvp_database)
        fixed_service = MarketingWorkflowService(mvp_database, queue=fixed_queue)
        if redis_mode != "unavailable":
            await graph_queue.client.delete(FIXED_WAKEUP_KEY, GRAPH_WAKEUP_KEY)
        actor, owner, fixed, rid = await seed(mvp_database, runtime, fixed_service)
        process = None
        try:
            _, graph_jobs, _ = await state(mvp_database, rid)
            assert len(graph_jobs) == 2  # Initial market/competitor research persisted before execution.
            fixed_id = fixed["jobs"][0]["job_id"]
            graph_id = graph_jobs[0].job_id
            # PostgreSQL boundary, including explicitly wrong hints (no ID heuristics).
            assert not await MarketingWorker(fixed_service, fixed_executors()).once(graph_id)
            assert not await runtime.create_worker().once(fixed_id)
            async with mvp_database() as session:
                assert (await session.get(JobExecution, graph_id)).attempts == 0
                assert (await session.get(JobExecution, fixed_id)).attempts == 0
            if redis_mode != "unavailable":
                assert await fixed_queue.wait() == fixed_id
                assert {await graph_queue.wait(), await graph_queue.wait()} == {j.job_id for j in graph_jobs}
                # A wrong/stale Redis hint must be harmless even with a pending fixed Job.
                await graph_queue.wake(fixed_id)
                assert not await runtime.create_worker().once(await graph_queue.wait())
                await graph_queue.wake("unknown-stale-job")
                assert not await runtime.create_worker().once(await graph_queue.wait())
                if redis_mode == "available":
                    await fixed_queue.wake(fixed_id)
                    for job in graph_jobs:
                        await graph_queue.wake(job.job_id)
                # 'lost' intentionally has no hints left. Both lanes must scan DB.
            process = asyncio.create_task(main(sessions=mvp_database, queue_factory=queue_factory,
                graph_factory=factory, fixed_executor_factory=fixed_executors))
            async def complete():
                graph = (await state(mvp_database, rid))[0]
                fixed_status = await fixed_service.status(actor, fixed["run_id"])
                return graph.status == "completed" and fixed_status["status"] == "awaiting_creative"
            await wait_until(complete)
            assert not process.done()
            _, jobs, artifacts = await state(mvp_database, rid)
            assert len(jobs) == len(artifacts) == len(model.calls) == len(provider_calls) == 5
            assert all(j.kind == "orchestration.module" and j.status is JobStatus.SUCCEEDED for j in jobs)
            fixed_run, fixed_jobs, _ = await state(mvp_database, fixed["run_id"])
            assert len(fixed_jobs) == 1 and fixed_jobs[0].kind == "marketing.step"
            assert fixed_jobs[0].status is JobStatus.SUCCEEDED
            assert all(c.is_closed for c in clients)
        finally:
            if process is not None:
                process.cancel()
                await asyncio.gather(process, return_exceptions=True)
            await cleanup_pair(mvp_database, fixed, rid, owner)
            if redis_mode != "unavailable":
                await graph_queue.client.delete(FIXED_WAKEUP_KEY, GRAPH_WAKEUP_KEY)
            for q in queues:
                await q.close()
    asyncio.run(exercise())


def test_shutdown_leaves_both_active_leases_recoverable(mvp_database):
    from tests.test_production_graph_worker import queue
    async def exercise():
        graph_started, fixed_started = asyncio.Event(), asyncio.Event()
        async def graph_model(**kwargs):
            graph_started.set()
            await asyncio.Event().wait()
        async def fixed_model(**kwargs):
            fixed_started.set()
            await asyncio.Event().wait()
        factory = partial(build_production_graph_runtime, model_call=graph_model, analyzer=analyzer())
        runtime = factory(sessions=mvp_database, queue=queue())
        fixed_service = MarketingWorkflowService(mvp_database)
        actor, owner, fixed, rid = await seed(mvp_database, runtime, fixed_service)
        # Only in-memory test queues here; PostgreSQL claims remain real.
        def queue_factory(*, key):
            result = queue(key)
            async def wait():
                await asyncio.Event().wait()
            result.wait = wait
            return result
        process = asyncio.create_task(main(sessions=mvp_database, queue_factory=queue_factory,
            graph_factory=factory, fixed_executor_factory=lambda: fixed_executors(fixed_model)))
        try:
            await asyncio.wait_for(asyncio.gather(graph_started.wait(), fixed_started.wait()), 10)
            process.cancel()
            with pytest.raises(asyncio.CancelledError):
                await process
            all_jobs = (await state(mvp_database, rid))[1] + (await state(mvp_database, fixed["run_id"]))[1]
            active = [j for j in all_jobs if j.status is JobStatus.RUNNING]
            assert {j.kind for j in active} == {"marketing.step", "orchestration.module"}
            assert all(j.status is not JobStatus.FAILED for j in all_jobs)
            async with mvp_database() as session, session.begin():
                for job in active:
                    lease = await session.get(JobExecution, job.job_id)
                    assert lease.attempts == 1 and lease.claim_token and lease.lease_until
                    lease.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
            replacement = build_production_graph_runtime(sessions=mvp_database, queue=queue(),
                model_call=StrategyModel(use_parents=True), analyzer=analyzer())
            for job in active:
                worker = (replacement.create_worker() if job.kind == "orchestration.module"
                          else MarketingWorker(fixed_service, fixed_executors()))
                assert await worker.once(job.job_id)
            async with mvp_database() as session:
                for job in active:
                    lease = await session.get(JobExecution, job.job_id)
                    assert lease.attempts == 2 and lease.claim_token is None
        finally:
            process.cancel()
            await asyncio.gather(process, return_exceptions=True)
            await cleanup_pair(mvp_database, fixed, rid, owner)
    asyncio.run(exercise())


@pytest.mark.parametrize("status,body,attempts", [(503, {"error": "SECRET"}, 3),
    (401, {"error": "SECRET"}, 1), (200, {"output_text": "malformed SECRET"}, 1)])
def test_production_transport_retry_budget_is_owned_only_by_job_execution(mvp_database, monkeypatch, status, body, attempts):
    from tests.test_graph_model_adapter import install_transport
    from tests.test_production_graph_worker import queue
    async def exercise():
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(status, json=body)
        clients = install_transport(monkeypatch, respond)
        runtime = build_production_graph_runtime(sessions=mvp_database, queue=queue(), analyzer=analyzer())
        clock = Clock()
        runtime.service.clock = clock
        rid = uuid.uuid4().hex
        async with mvp_database() as session, session.begin():
            owner = User(telegram_id=int(uuid.uuid4().hex[:12], 16))
            session.add(owner)
            await session.flush()
            owner_id = owner.id
        try:
            await runtime.service.start_compiled_run(owner_id=owner_id, run_id=rid,
                plan=strategy_compiled(executors=runtime.executors))
            worker = runtime.create_worker()
            for attempt in range(attempts):
                assert await worker.once()
                assert not await worker.once()  # No retry until durable available_at.
                clock.tick(11)
            assert not await worker.once()
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "failed" and len(jobs) == 1 and not artifacts
            assert jobs[0].status is JobStatus.FAILED
            assert len(calls) == attempts and all(c.is_closed for c in clients)
            assert "SECRET" not in str(run.state_json) + str(jobs[0].error)
            async with mvp_database() as session:
                assert (await session.get(JobExecution, jobs[0].job_id)).attempts == attempts
        finally:
            await cleanup(mvp_database, rid, owner_id)
    asyncio.run(exercise())
