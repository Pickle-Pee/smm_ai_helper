"""Strategy A-F, durable barriers/recovery and real outer gates; fake providers."""
import asyncio
from dataclasses import replace
import json
import os
import subprocess
import sys
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.marketing_copilot.application_contracts import CopilotRequest, ResultKind
from app.marketing_copilot.context_resolver import ContextEntry
from app.marketing_copilot.contracts import IntentKind
from app.marketing_copilot.factory import build_marketing_copilot_service
from app.models import JobStatus, MarketingArtifact, MarketingRun, OrchestrationPlanRecord, User
from app.module_execution import ModuleExecutorDispatcher
from app.orchestration_runtime.contracts import module_job_id
from app.orchestration_runtime.errors import StartIdentityConflict
from app.orchestration_runtime.serialization import plan_to_json
from app.orchestration_runtime.service import GraphExecutionService, evaluate_result
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests.postgresql_support import mvp_database
from tests.test_graph_postgresql import Clock, cleanup, state
from tests.test_copilot_application import intent_model
from tests.test_strategy_builder import strategy_context, strategy_executors, strategy_compiled, StrategyModel
from tests.test_strategy_intelligence import IntelligenceModel


async def setup(db, competitors=2, market=True, *, max_attempts=3):
    model = StrategyModel(use_parents=True)
    executors = strategy_executors(model)
    context = strategy_context(tuple(f"https://competitor{i}.example/" for i in range(competitors)), market)
    clock = Clock()
    queue = type("DownQueue", (), {"wake": AsyncMock(side_effect=ConnectionError("offline"))})()
    service = GraphExecutionService(db, executors=executors, clock=clock, queue=queue, max_attempts=max_attempts)
    async with db() as session, session.begin():
        user = User(telegram_id=int(uuid.uuid4().hex[:12], 16))
        session.add(user)
        await session.flush()
        owner = user.id
    copilot = build_marketing_copilot_service(intent_model=intent_model(IntentKind.MARKETING_STRATEGY),
        executor_registry=executors, graph_service=service, registry_version="1.2.0")
    request = CopilotRequest(actor_id=owner, request_id=uuid.uuid4().hex, message="Build a strategy",
        current_request=tuple(ContextEntry(f.input_key.value if f.input_key else f.label, f) for f in context.known_facts),
        available_tools=context.available_tools)
    response = await copilot.execute(request)
    assert response.kind is ResultKind.WORKFLOW_STARTED and not model.calls
    assert (await copilot.execute(request)).workflow.run_id == response.workflow.run_id
    return service, clock, response.workflow.run_id, owner, model


async def execute_node(service, rid, node):
    assert await ModuleGraphWorker(service).once(module_job_id(rid, 1, node))


async def drain(service, db, rid):
    for _ in range(12):
        run, jobs, _ = await state(db, rid)
        if run.status in {"completed", "completed_with_limitations", "failed", "blocked"}:
            return
        pending = [j for j in jobs if j.status is JobStatus.PENDING]
        assert pending, [(j.workflow_step, j.status, j.error) for j in jobs]
        for job in pending:
            await execute_node(service, rid, job.workflow_step)
    pytest.fail("graph did not terminate")


@pytest.mark.parametrize("competitors,market", [(2, True), (2, False), (0, False), (3, True)])
def test_strategy_full_no_market_no_competitors_and_maximum_graph(mvp_database, competitors, market):
    async def exercise():
        service, clock, rid, owner, model = await setup(mvp_database, competitors, market)
        try:
            _, jobs, _ = await state(mvp_database, rid)
            assert len(jobs) == (competitors + market or 1)
            assert {j.workflow_step for j in jobs} == (
                {f"competitor_analysis_{i}" for i in range(1, competitors + 1)} |
                ({"market_analysis"} if market else set()) or {"positioning"})
            await drain(service, mvp_database, rid)
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "completed", [(j.workflow_step, j.error) for j in jobs]
            assert len(artifacts) == competitors + market + 3
            assert run.error is None
            assert all(j.status is JobStatus.SUCCEEDED for j in jobs)
            if not market:
                assert {"code": "market_research_not_supplied"} in run.state_json["limitations"]
                assert "market_analysis" not in {j.workflow_step for j in jobs}
            calls = [json.loads(c["text"]) for c in model.calls]
            cmo = next(c for c in calls if "main_growth_constraint" in c["expected_outputs"])
            ancestors = {u["producer_node_id"] for u in cmo["upstream_results"]}
            assert ancestors == {j.workflow_step for j in jobs} - {"virtual_cmo", "experiments"}
            assert "Evidence coverage" in str(cmo["context"]["open_questions"])
            assert not any("evidence_coverage" in str(e) for e in cmo["local_evidence"])
            if market:
                market_call = next(c for c in calls if "market_size_if_supported" in c["expected_outputs"])
                assert market_call["upstream_results"] == []
            async with mvp_database() as session:
                saved = await session.get(OrchestrationPlanRecord, (rid, 1))
                assert saved.registry_version == "1.2.0"
                assert saved.compiled_plan_json["schema_version"] == "compiled_execution_plan.v2"
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


@pytest.mark.parametrize("failed_node", ["competitor_analysis_2", "market_analysis", "experiments"])
@pytest.mark.parametrize("failure", ["module_blocked", "quality_rejected", "execution_invalid", "provider_transient", "attempts_exhausted"])
def test_optional_terminal_outcomes_preserve_strategy(mvp_database, failed_node, failure):
    async def exercise():
        service, clock, rid, owner, model = await setup(mvp_database, 3, True, max_attempts=2)
        try:
            if failed_node == "experiments":
                for node in ("market_analysis", "competitor_analysis_1", "competitor_analysis_2", "competitor_analysis_3", "positioning", "virtual_cmo"):
                    await execute_node(service, rid, node)
            item = await service.claim(module_job_id(rid, 1, failed_node))
            if failure == "attempts_exhausted":
                clock.tick()
                assert await service.claim(item.job_id)
                clock.tick()
                assert await service.claim(item.job_id) is None
            elif failure == "provider_transient":
                assert await service.fail(item, code=failure, retryable=True)
                clock.tick()
                retry = await service.claim(item.job_id)
                assert await service.fail(retry, code=failure, retryable=True)
            else:
                assert await service.fail(item, code=failure)
            await drain(service, mvp_database, rid)
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "completed_with_limitations", [(j.workflow_step, j.error) for j in jobs]
            assert run.error is None
            assert next(j for j in jobs if j.workflow_step == failed_node).status is JobStatus.FAILED
            assert "virtual_cmo" in {a.step for a in artifacts}
            assert failed_node not in {a.step for a in artifacts}
            assert {"code": "optional_node_failed", "node_id": failed_node, "reason": failure} in run.state_json["limitations"]
            for call in model.calls:
                data = json.loads(call["text"])
                assert failed_node not in {u["producer_node_id"] for u in data["upstream_results"]}
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


@pytest.mark.parametrize("node", ["positioning", "virtual_cmo"])
@pytest.mark.parametrize("failure", ["module_blocked", "quality_rejected", "execution_invalid"])
def test_required_failure_stops_downstream_and_keeps_research(mvp_database, node, failure):
    async def exercise():
        service, clock, rid, owner, _ = await setup(mvp_database)
        try:
            for research in ("market_analysis", "competitor_analysis_1", "competitor_analysis_2"):
                await execute_node(service, rid, research)
            if node == "virtual_cmo":
                await execute_node(service, rid, "positioning")
            item = await service.claim(module_job_id(rid, 1, node))
            assert await service.fail(item, code=failure)
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == ("blocked" if failure == "module_blocked" else "failed")
            assert len(artifacts) == (3 if node == "positioning" else 4)
            assert "experiments" not in {j.workflow_step for j in jobs}
            if node == "positioning":
                assert "virtual_cmo" not in {j.workflow_step for j in jobs}
            assert await service.advance(rid) == ()
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_optional_barrier_concurrent_advance_fencing_and_process_restart(mvp_database):
    async def exercise():
        service, clock, rid, owner, _ = await setup(mvp_database, 3, False)
        try:
            await asyncio.gather(*(service.advance(rid) for _ in range(4)))
            first = await service.claim(module_job_id(rid, 1, "competitor_analysis_1"))
            second = await service.claim(module_job_id(rid, 1, "competitor_analysis_2"))
            slow = await service.claim(module_job_id(rid, 1, "competitor_analysis_3"))
            assert all((first, second, slow))
            binding, request = await service.load_work(first)
            result = await ModuleExecutorDispatcher(service.executors).dispatch(binding, request)
            assert await service.finish(first, result, evaluate_result(first.job_id, result, request.upstream_results))
            assert await service.fail(second, code="module_blocked")
            await asyncio.gather(service.advance(rid), service.advance(rid))
            _, jobs, _ = await state(mvp_database, rid)
            assert len(jobs) == 3  # Slow branch is still running: positioning must wait.
            clock.tick()
            replacement = await service.claim(slow.job_id)
            assert not await service.fail(slow, code="execution_invalid")
            assert await service.fail(replacement, code="execution_invalid")
            await asyncio.gather(*(service.advance(rid) for _ in range(4)))
            _, jobs, _ = await state(mvp_database, rid)
            assert sum(j.workflow_step == "positioning" for j in jobs) == 1
            script = '''
import asyncio, os, sys
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.orchestration_runtime.service import GraphExecutionService
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests.test_strategy_builder import strategy_executors
async def main():
    engine = create_async_engine(os.environ["MVP_TEST_DATABASE_URL"])
    service = GraphExecutionService(async_sessionmaker(engine, expire_on_commit=False), executors=strategy_executors(),
        clock=lambda: datetime.fromisoformat(sys.argv[1]))
    worker = ModuleGraphWorker(service)
    for _ in range(3):
        assert await worker.once()  # DB due scan, no Redis or in-memory progress.
    await engine.dispose()
asyncio.run(main())
'''
            completed = await asyncio.to_thread(subprocess.run, [sys.executable, "-c", script, clock.now.isoformat()],
                capture_output=True, text=True, timeout=60, env=os.environ.copy())
            assert completed.returncode == 0, completed.stderr
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "completed_with_limitations"
            assert len(jobs) == 6 and len(artifacts) == 4
            assert {"code": "only_one_competitor_analyzed"} in run.state_json["limitations"]
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_compiled_dedupe_identity_replay_and_conflict(mvp_database):
    async def exercise():
        executors = strategy_executors()
        service = GraphExecutionService(mvp_database, executors=executors)
        rid = uuid.uuid4().hex
        async with mvp_database() as session, session.begin():
            user = User(telegram_id=int(uuid.uuid4().hex[:12], 16))
            session.add(user)
            await session.flush()
            owner = user.id
        try:
            first = strategy_compiled(strategy_context(("https://A.example:443", "https://a.example/")))
            second = strategy_compiled(strategy_context(("https://a.example/",)))
            assert first == second
            await asyncio.gather(*(service.start_compiled_run(owner_id=owner, run_id=rid, plan=p) for p in (first, second)))
            _, jobs, _ = await state(mvp_database, rid)
            assert len(jobs) == 1
            with pytest.raises(StartIdentityConflict):
                await service.start_compiled_run(owner_id=owner, run_id=rid, plan=strategy_compiled())
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["source", "blocked", "partial_quality"])
def test_worker_optional_failures_do_not_leak_errors_or_partial_artifacts(mvp_database, monkeypatch, failure):
    async def exercise():
        service, clock, rid, owner, _ = await setup(mvp_database, 2, False)
        try:
            target = module_job_id(rid, 1, "competitor_analysis_2")
            executor = service.executors.resolve("competitor_analysis.v1")
            original = executor.execute
            async def execute(request):
                if request.execution_id == target:
                    if failure == "source":
                        raise ValueError("RAW-PROVIDER-SECRET")
                    if failure == "blocked":
                        from app.module_execution.executors.common import blocked
                        from app.marketing_orchestrator.quality_gates.contracts import BlockingReason
                        return blocked(request, executor.schema_version, BlockingReason.TOOL_UNAVAILABLE, "RAW-PROVIDER-SECRET")
                return await original(request)
            executor.execute = execute
            if failure == "partial_quality":
                def partial(job_id, result, upstream):
                    quality = evaluate_result(job_id, result, upstream)
                    if job_id == target:
                        assert result.normalized_result.result_id in quality["accepted_result_ids"]
                        quality["accepted_claim_ids"].remove(result.normalized_result.claims[0].claim_id)
                    return quality
                monkeypatch.setattr("app.orchestration_runtime.worker.evaluate_result", partial)
            await drain(service, mvp_database, rid)
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "completed_with_limitations"
            assert next(j for j in jobs if j.job_id == target).status is JobStatus.FAILED
            assert "competitor_analysis_2" not in {a.step for a in artifacts}
            assert "RAW-PROVIDER-SECRET" not in str(run.state_json) + str([j.error for j in jobs])
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_research_providers_overlap_without_holding_database_transactions(mvp_database):
    async def exercise():
        service, clock, rid, owner, model = await setup(mvp_database, 2, True)
        release, started = asyncio.Event(), asyncio.Queue()
        tasks = []
        async def waiting_model(**kwargs):
            await started.put(True)
            await release.wait()
            return await model(**kwargs)
        for key in ("competitor_analysis.v1", "market_analysis.v1"):
            service.executors.resolve(key)._model_call = waiting_model
        try:
            for node in ("market_analysis", "competitor_analysis_1", "competitor_analysis_2"):
                tasks.append(asyncio.create_task(ModuleGraphWorker(service).once(module_job_id(rid, 1, node))))
                await asyncio.wait_for(started.get(), timeout=10)
            _, jobs, artifacts = await state(mvp_database, rid)
            assert len(jobs) == 3 and all(j.status is JobStatus.RUNNING for j in jobs) and not artifacts
            release.set()
            assert all(await asyncio.gather(*tasks))
            await asyncio.gather(service.advance(rid), service.advance(rid))
            _, jobs, artifacts = await state(mvp_database, rid)
            assert len(artifacts) == 3 and sum(j.workflow_step == "positioning" for j in jobs) == 1
            await drain(service, mvp_database, rid)
            assert (await state(mvp_database, rid))[0].status == "completed"
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_all_optional_research_failed_still_uses_first_party_positioning(mvp_database):
    async def exercise():
        service, clock, rid, owner, model = await setup(mvp_database)
        try:
            for node in ("market_analysis", "competitor_analysis_1", "competitor_analysis_2"):
                item = await service.claim(module_job_id(rid, 1, node))
                assert await service.fail(item, code="module_blocked")
            await drain(service, mvp_database, rid)
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "completed_with_limitations"
            assert {a.step for a in artifacts} == {"positioning", "virtual_cmo", "experiments"}
            assert json.loads(model.calls[0]["text"])["upstream_results"] == []
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_optional_policy_cannot_tolerate_corrupt_persisted_graph(mvp_database):
    async def exercise():
        service, clock, rid, owner, _ = await setup(mvp_database)
        try:
            await execute_node(service, rid, "competitor_analysis_1")
            async with mvp_database() as session, session.begin():
                artifact = await session.scalar(select(MarketingArtifact).where(MarketingArtifact.run_id == rid))
                artifact.payload_json = {}
            await execute_node(service, rid, "competitor_analysis_2")
            run, jobs, _ = await state(mvp_database, rid)
            assert run.status == "failed" and run.error == "invalid_persisted_graph"
            assert "positioning" not in {j.workflow_step for j in jobs}
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())
