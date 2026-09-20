"""Release boundaries: real SQL, HTTP/worker composition, bounded offline stress."""
import asyncio
import copy
from datetime import datetime
import json
import os
import time
from types import SimpleNamespace
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.marketing_copilot.contracts import IntentKind
from app.models import JobExecution, JobStatus, MarketingRun, OrchestrationPlanRecord, User
from app.orchestration_runtime.composition import build_production_graph_runtime
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests.postgresql_support import mvp_database
from tests.test_copilot_api import application, headers, queue
from tests.test_copilot_api_postgresql import configured, payload, remove_actor
from tests.test_graph_postgresql import Clock, state
from tests.test_module_executors import analyzer
from tests.test_strategy_builder import StrategyModel


async def drain(api, db, rid):
    for _ in range(10):
        run, jobs, _ = await state(db, rid)
        if run.status in {"completed", "completed_with_limitations", "blocked", "failed"}:
            return
        for job in jobs:
            if job.status is JobStatus.PENDING:
                await ModuleGraphWorker(api.copilot.graph_service).once(job.job_id)
    pytest.fail("Graph failed to reach a terminal state")


@pytest.mark.parametrize("conflict", [False, True])
def test_ten_concurrent_execute_authoritative_identity(mvp_database, monkeypatch, conflict):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        # Exercise a bounded production-style pool, not ten independent NullPool connections.
        engine = create_async_engine(os.environ["MVP_TEST_DATABASE_URL"], pool_size=5, max_overflow=0, pool_timeout=10)
        db = async_sessionmaker(engine, expire_on_commit=False)
        actor, model = int(uuid.uuid4().hex[:12], 16), StrategyModel(use_parents=True)
        api = configured(db, IntentKind.MARKETING_STRATEGY, module_model=model)
        request = payload()
        changed = copy.deepcopy(request)
        changed["context"]["product_truth"] = "A different authoritative product capability"
        bodies = [changed if conflict and i % 2 else request for i in range(10)]
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                began = time.monotonic()
                async with asyncio.timeout(30):
                    responses = await asyncio.gather(*(client.post("/copilot/execute", headers=headers(actor), json=b) for b in bodies))
                assert {r.status_code for r in responses} == ({202, 409} if conflict else {202})
                successful = [r.json() for r in responses if r.status_code == 202]
                assert len(successful) == (5 if conflict else 10)
                assert len({r["run_id"] for r in successful}) == 1
                rid = successful[0]["run_id"]
                if conflict:
                    assert all(r.json()["code"] == "request_conflict" for r in responses if r.status_code == 409)
                    # Every caller of the winning identity wins, every other loses.
                    assert len({r.status_code for r in responses[::2]}) == len({r.status_code for r in responses[1::2]}) == 1
                assert not model.calls  # 202 starts Jobs; never executes a module inline.
                async with db() as session:
                    runs = (await session.scalars(select(MarketingRun).join(User).where(User.telegram_id == actor))).all()
                    plans = (await session.scalars(select(OrchestrationPlanRecord).where(OrchestrationPlanRecord.run_id == rid))).all()
                    assert len(runs) == len(plans) == 1 and plans[0].revision == 1
                    winning = next(b for b, r in zip(bodies, responses) if r.status_code == 202)
                    assert winning["context"]["product_truth"] in json.dumps(plans[0].compiled_plan_json)
                await drain(api, db, rid)
                run, jobs, artifacts = await state(db, rid)
                assert run.status == "completed" and len(jobs) == len(artifacts) == len(model.calls) == 3
                assert len({j.job_id for j in jobs}) == 3
                assert len({a.artifact_key for a in artifacts}) == 3
                print(f"execute stress: 10 callers, pool=5/overflow=0, conflict={conflict}, elapsed={time.monotonic()-began:.2f}s")
        finally:
            await remove_actor(db, actor)
            await engine.dispose()
    asyncio.run(check())


def test_recent_owner_scope_pagination_and_projection(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        api = configured(mvp_database, IntentKind.MARKETING_STRATEGY)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                ids = [(await client.post("/copilot/execute", headers=headers(actor), json=payload())).json()["run_id"] for _ in range(3)]
                async with mvp_database() as session, session.begin():
                    for rid in ids:
                        run = await session.get(MarketingRun, rid)
                        run.created_at = datetime(2026, 1, 1)  # Deterministic tie break.
                        run.input_json = run.state_json = {"secret": "PRIVATE_CONTEXT"}
                        run.error = "PRIVATE_ERROR"
                    session.add(MarketingRun(run_id=uuid.uuid4().hex, user_id=run.user_id,
                        workflow_type="marketing.v1", status="queued"))
                first = await client.get("/copilot/runs?limit=2", headers=headers(actor))
                assert first.status_code == 200
                page = first.json()
                second = (await client.get(f"/copilot/runs?limit=2&offset={page['next_offset']}", headers=headers(actor))).json()
                assert [v["run_id"] for v in page["items"] + second["items"]] == sorted(ids, reverse=True)
                assert second["next_offset"] is None
                for item in page["items"]:
                    assert set(item) == {"run_id", "status", "created_at", "updated_at"}
                    assert item["created_at"].endswith("Z")
                assert "PRIVATE" not in first.text
                assert (await client.get("/copilot/runs", headers=headers(actor + 1))).json()["items"] == []
                assert (await client.get("/copilot/runs")).status_code == 401
                for query in ("limit=0", "limit=51", "offset=-1", "offset=10001", "offset=secret"):
                    invalid = await client.get("/copilot/runs?" + query, headers=headers(actor))
                    assert invalid.status_code == 422 and "secret" not in invalid.text
                for rid in ("bad", "a" * 65):
                    assert (await client.get("/copilot/runs/" + rid, headers=headers(actor))).status_code == 422
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


def test_read_snapshot_survives_commit_between_run_and_artifact_selects(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        api = configured(mvp_database, IntentKind.MARKETING_STRATEGY, module_model=StrategyModel(use_parents=True))
        graph = api.copilot.graph_service
        entered, resume = asyncio.Event(), asyncio.Event()
        async def blocked_plan(session, rid):
            assert await session.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            assert await session.scalar(text("SHOW transaction_read_only")) == "on"
            entered.set()
            await resume.wait()
            return await graph._plan(session, rid)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                response = await client.post("/copilot/execute", headers=headers(actor), json=payload())
                rid, url = response.json()["run_id"], response.json()["status_url"]
                api.reader.graph = SimpleNamespace(_plan=blocked_plan, _graph_state=graph._graph_state)
                reading = asyncio.create_task(client.get(url, headers=headers(actor)))
                try:
                    await asyncio.wait_for(entered.wait(), 10)
                    # Completion must progress while the reader keeps the old snapshot.
                    await asyncio.wait_for(drain(api, mvp_database, rid), 15)
                    resume.set()
                    old = await asyncio.wait_for(reading, 10)
                finally:
                    resume.set()
                    await asyncio.gather(reading, return_exceptions=True)
                assert old.status_code == 200 and old.json()["status"] == "QUEUED"
                assert old.json()["strategy"] is None and old.json()["details"] == []
                fresh = await client.get(url, headers=headers(actor))
                assert fresh.json()["status"] == "COMPLETED" and fresh.json()["strategy"]
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


def test_twenty_pollers_are_read_only_and_do_not_block_worker(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        engine = create_async_engine(os.environ["MVP_TEST_DATABASE_URL"], pool_size=5, max_overflow=0, pool_timeout=10)
        db = async_sessionmaker(engine, expire_on_commit=False)
        actor, model = int(uuid.uuid4().hex[:12], 16), StrategyModel(use_parents=True)
        api = configured(db, IntentKind.MARKETING_STRATEGY, module_model=model)
        statements = []
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                started = (await client.post("/copilot/execute", headers=headers(actor), json=payload())).json()
                rid, url = started["run_id"], started["status_url"]
                before = await state(db, rid)
                wakes = api.queue.wake.await_count
                def sql(_conn, _cursor, statement, *_args):
                    statements.append(statement.strip().upper())
                event.listen(engine.sync_engine, "before_cursor_execute", sql)
                began = time.monotonic()
                async with asyncio.timeout(30):
                    reads = await asyncio.gather(*(client.get(url if i % 2 else "/copilot/runs", headers=headers(actor)) for i in range(20)))
                event.remove(engine.sync_engine, "before_cursor_execute", sql)
                assert all(r.status_code == 200 for r in reads)
                assert all(s.startswith(("SELECT", "SET TRANSACTION")) and "FOR UPDATE" not in s for s in statements)
                assert not model.calls and api.queue.wake.await_count == wakes
                after = await state(db, rid)
                assert before[0].updated_at == after[0].updated_at
                assert [(j.version, j.updated_at) for j in before[1]] == [(j.version, j.updated_at) for j in after[1]]
                async with asyncio.timeout(30):
                    combined = await asyncio.gather(drain(api, db, rid), *(client.get(url, headers=headers(actor)) for _ in range(20)))
                assert all(r.status_code == 200 for r in combined[1:])
                assert (await state(db, rid))[0].status == "completed" and len(model.calls) == 3
                print(f"polling stress: 20 readers, pool=5/overflow=0, worker progressed, elapsed={time.monotonic()-began:.2f}s")
        finally:
            await remove_actor(db, actor)
            await engine.dispose()
    asyncio.run(check())


@pytest.mark.parametrize("crash_point", ["during_provider", "before_persistence", "late_completion"])
def test_worker_crash_and_stale_finish_preserve_one_accepted_result(mvp_database, monkeypatch, crash_point):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        entered, release = asyncio.Event(), asyncio.Event()
        model = StrategyModel(use_parents=True)
        async def provider(**kw):
            if crash_point == "during_provider":
                entered.set()
                await release.wait()
            return await model(**kw)
        api = configured(mvp_database, IntentKind.MARKETING_STRATEGY, module_model=provider)
        service, clock = api.copilot.graph_service, Clock()
        service.clock = clock
        original_finish, completions = service.finish, []
        async def paused_finish(item, result, quality):
            entered.set()
            await release.wait()
            accepted = await original_finish(item, result, quality)
            completions.append(accepted)
            return accepted
        if crash_point != "during_provider":
            service.finish = paused_finish
        task = None
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                started = (await client.post("/copilot/execute", headers=headers(actor), json=payload())).json()
                rid = started["run_id"]
                job_id = (await state(mvp_database, rid))[1][0].job_id
                task = asyncio.create_task(ModuleGraphWorker(service).once(job_id))
                await asyncio.wait_for(entered.wait(), 10)
                if crash_point != "late_completion":
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                run, jobs, artifacts = await state(mvp_database, rid)
                assert jobs[0].status is JobStatus.RUNNING and not artifacts and run.status == "running"
                replacement = build_production_graph_runtime(sessions=mvp_database, queue=queue(),
                    model_call=StrategyModel(use_parents=True), analyzer=analyzer())
                replacement.service.clock = clock
                clock.tick(400)
                assert await replacement.create_worker().once(job_id)
                release.set()
                if crash_point == "late_completion":
                    assert await asyncio.wait_for(task, 10)
                    assert completions == [False]  # Expired token can never persist.
                async with mvp_database() as session:
                    assert (await session.get(JobExecution, job_id)).attempts == 2
                api.copilot.graph_service = replacement.service
                await drain(api, mvp_database, rid)
                run, jobs, artifacts = await state(mvp_database, rid)
                assert run.status == "completed" and len(jobs) == len(artifacts) == 3
                assert len({a.artifact_key for a in artifacts}) == 3
                assert (await client.get(started["status_url"], headers=headers(actor))).json()["strategy"]
        finally:
            release.set()
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


@pytest.mark.parametrize("redis_down_at", ["before_start", "during_run"])
def test_api_commits_and_worker_scans_through_redis_failure(mvp_database, monkeypatch, redis_down_at):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        api = configured(mvp_database, IntentKind.MARKETING_STRATEGY, module_model=StrategyModel(use_parents=True))
        if redis_down_at == "before_start":
            api.queue.wake.side_effect = ConnectionError("SECRET redis failure")
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                started = await client.post("/copilot/execute", headers=headers(actor), json=payload())
                assert started.status_code == 202
                rid = started.json()["run_id"]
                if redis_down_at == "during_run":
                    job = (await state(mvp_database, rid))[1][0]
                    assert await ModuleGraphWorker(api.copilot.graph_service).once(job.job_id)
                    api.queue.wake.side_effect = ConnectionError("SECRET redis failure")
                # No supplied hint; claims use the same DB scan as production run_lane.
                for _ in range(4):
                    if (await state(mvp_database, rid))[0].status == "completed":
                        break
                    assert await ModuleGraphWorker(api.copilot.graph_service).once()
                assert (await state(mvp_database, rid))[0].status == "completed"
                assert (await client.get("/copilot/runs", headers=headers(actor))).json()["items"][0]["run_id"] == rid
                assert (await client.get(started.json()["status_url"], headers=headers(actor))).json()["strategy"]
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


def test_single_timeout_is_bounded_safe_and_never_starts_graph(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor, entered = int(uuid.uuid4().hex[:12], 16), asyncio.Event()
        async def provider(**_kw):
            entered.set()
            await asyncio.Event().wait()
        api = configured(mvp_database, IntentKind.POST_GENERATION, module_model=provider)
        monkeypatch.setattr(settings, "GRAPH_TIMEOUT_SECONDS", .05)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                async with asyncio.timeout(5):
                    result = await client.post("/copilot/execute", headers=headers(actor), json=payload())
                assert entered.is_set() and result.status_code == 503
                assert result.json()["code"] == "temporarily_unavailable"
                assert (await client.get("/copilot/runs", headers=headers(actor))).json()["items"] == []
                api.queue.wake.assert_not_awaited()
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


def test_two_production_graph_workers_overlap_research_and_keep_barrier(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        model, both_started, release = StrategyModel(use_parents=True), asyncio.Event(), asyncio.Event()
        first_entered = asyncio.Event()
        active = 0
        async def provider(**kw):
            nonlocal active
            active += 1
            first_entered.set()
            if active == 2:
                both_started.set()
            await release.wait()
            return await model(**kw)
        api = configured(mvp_database, IntentKind.MARKETING_STRATEGY, module_model=provider)
        graph = api.copilot.graph_service
        tasks = []
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                started = await client.post("/copilot/execute", headers=headers(actor), json=payload(
                    competitor_urls=[f"https://competitor{i}.example/" for i in range(3)],
                    market_sources=[{"title": "Research", "excerpt": "Clinics report appointment delays."}]))
                assert started.status_code == 202
                rid = started.json()["run_id"]
                # Claim one root, then start a second lane after the first provider
                # entered: real concurrency, no transaction spans provider work.
                tasks.append(asyncio.create_task(ModuleGraphWorker(graph).once()))
                await asyncio.wait_for(first_entered.wait(), 10)
                tasks.append(asyncio.create_task(ModuleGraphWorker(graph).once()))
                await asyncio.wait_for(both_started.wait(), 10)
                _, jobs, artifacts = await state(mvp_database, rid)
                assert len(jobs) == 4 and not artifacts
                assert len([j for j in jobs if j.status is JobStatus.RUNNING]) == 2
                assert "positioning" not in {j.workflow_step for j in jobs}
                # All duplicate claims for leased Jobs must be rejected.
                claimed = [j.job_id for j in jobs if j.status is JobStatus.RUNNING]
                assert await asyncio.gather(*(graph.claim(j) for j in claimed * 5)) == [None] * 10
                release.set()
                assert all(await asyncio.gather(*tasks))
                await drain(api, mvp_database, rid)
                run, jobs, artifacts = await state(mvp_database, rid)
                assert run.status == "completed" and len(jobs) == len(artifacts) == len(model.calls) == 7
                final = (await client.get(started.json()["status_url"], headers=headers(actor))).json()
                assert final["strategy"] and final["experiments"]
                assert final["evidence_coverage"]["competitors_accepted"] == 3
        finally:
            release.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await remove_actor(mvp_database, actor)
    asyncio.run(check())
