"""Durable graph acceptance with real PostgreSQL and real executors; no providers."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select, func

from app.models import Job, JobExecution, JobStatus, MarketingArtifact, MarketingRun, OrchestrationPlanRecord, User, WorkflowDelivery
from app.module_execution import ModuleExecutorDispatcher
from app.module_registry import ModuleRegistry
from app.orchestration_runtime import PlanCompiler
from app.orchestration_runtime.contracts import module_job_id
from app.orchestration_runtime.errors import CompilationError, RuntimeContractError, StartIdentityConflict
from app.orchestration_runtime.serialization import plan_to_json
from app.orchestration_runtime.service import GraphExecutionService, evaluate_result
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests.graph_fakes import compiled, registry, source_plan, FakeModel
from tests.postgresql_support import mvp_database


class Clock:
    def __init__(self):
        self.now = datetime.now(timezone.utc)
    def __call__(self):
        return self.now
    def tick(self, seconds=400):
        self.now += timedelta(seconds=seconds)


async def setup(db, model=None, **kwargs):
    clock = Clock()
    executors = registry(model)
    service = GraphExecutionService(db, executors=executors, clock=clock, **kwargs)
    run_id = uuid.uuid4().hex
    async with db() as session, session.begin():
        user = User(telegram_id=int(uuid.uuid4().hex[:12], 16))
        session.add(user)
        await session.flush()
        owner = user.id
    await service.start_compiled_run(owner_id=owner, run_id=run_id, plan=compiled(executors))
    return service, clock, run_id, owner


async def cleanup(db, run_id, owner):
    async with db() as session, session.begin():
        await session.execute(delete(MarketingRun).where(MarketingRun.run_id == run_id))
        await session.execute(delete(User).where(User.id == owner))


async def state(db, run_id):
    async with db() as session:
        run = await session.get(MarketingRun, run_id)
        jobs = (await session.scalars(select(Job).where(Job.marketing_run_id == run_id))).all()
        artifacts = (await session.scalars(select(MarketingArtifact).where(MarketingArtifact.run_id == run_id))).all()
        return run, jobs, artifacts


def test_real_graph_restart_redis_loss_and_concurrent_advance(mvp_database):
    async def exercise():
        queue = type("DownQueue", (), {"wake": AsyncMock(side_effect=ConnectionError("offline"))})()
        service, clock, rid, owner = await setup(mvp_database, queue=queue)
        try:
            run, jobs, artifacts = await state(mvp_database, rid)
            assert len(jobs) == 1 and jobs[0].workflow_step == "competitor_analysis" and not artifacts
            assert "context_packet" not in jobs[0].payload_json
            assert await ModuleGraphWorker(service).once(jobs[0].job_id)
            await asyncio.gather(service.advance(rid), service.advance(rid))
            run, jobs, artifacts = await state(mvp_database, rid)
            assert len(jobs) == 2 and len(artifacts) == 1
            assert sum(j.workflow_step == "positioning" for j in jobs) == 1
            # New composition has no process-local result, context or executor objects.
            model = FakeModel(use_parents=True)
            replacement = GraphExecutionService(mvp_database, executors=registry(model), clock=clock)
            assert await ModuleGraphWorker(replacement).once(module_job_id(rid, 1, "positioning"))
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "completed" and len(artifacts) == 2
            assert all(j.status is JobStatus.SUCCEEDED and j.version == 2 for j in jobs)
            import json
            data = json.loads(model.calls[0]["text"])
            assert data["upstream_results"][0]["producer_node_id"] == "competitor_analysis"
            assert data["allowed_parent_claim_ids"]
            assert await replacement.advance(rid) == ()
            async with mvp_database() as session:
                assert await session.scalar(select(func.count()).select_from(WorkflowDelivery).join(Job).where(Job.marketing_run_id == rid)) == 0
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_expired_claim_is_fenced_and_replacement_finishes_once(mvp_database):
    async def exercise():
        service, clock, rid, owner = await setup(mvp_database)
        try:
            job_id = module_job_id(rid, 1, "competitor_analysis")
            old = await service.claim(job_id)
            binding, request = await service.load_work(old)
            result = await ModuleExecutorDispatcher(service.executors).dispatch(binding, request)
            quality = evaluate_result(job_id, result, request.upstream_results)
            clock.tick()
            replacement = await service.claim(job_id)
            assert replacement.claim_token != old.claim_token
            assert not await service.finish(old, result, quality)
            assert not await service.fail(old, code="execution_invalid")
            assert await service.finish(replacement, result, quality)
            assert not await service.finish(replacement, result, quality)
            _, jobs, artifacts = await state(mvp_database, rid)
            assert len(artifacts) == 1 and len(jobs) == 2
            async with mvp_database() as session:
                assert (await session.get(JobExecution, job_id)).attempts == 2
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


@pytest.mark.parametrize("mode", ["blocked", "quality", "malformed", "terminal", "retry"])
def test_domain_failures_and_provider_retry(mvp_database, mode):
    async def exercise():
        model = FakeModel(use_parents=True)
        service, clock, rid, owner = await setup(mvp_database, model)
        try:
            executor = service.executors.resolve("competitor_analysis.v1")
            if mode == "blocked":
                executor._model_call = None
            elif mode == "quality":
                original = executor.execute
                from app.module_registry import ModuleResultStatus
                from app.marketing_orchestrator.quality_gates.contracts import FailureReason, EvidenceSufficiency
                from app.orchestration_runtime.serialization import result_to_json
                async def rejected(request):
                    result = await original(request)
                    return replace(result, payload=result_to_json(result)["payload"], normalized_result=replace(
                        result.normalized_result, claims=(), module_status=ModuleResultStatus.FAIL,
                        failure_reasons=frozenset({FailureReason.MODULE_DECLARED_FAILURE}),
                        evidence_sufficiency=EvidenceSufficiency.INSUFFICIENT))
                executor.execute = rejected
            elif mode == "malformed":
                executor._model_call = AsyncMock(return_value="not-json secret sentinel")
            elif mode in {"retry", "terminal"}:
                executor._model_call = AsyncMock(side_effect=TimeoutError("secret sentinel") if mode == "retry" else ValueError("secret sentinel"))
            job_id = module_job_id(rid, 1, "competitor_analysis")
            worker = ModuleGraphWorker(service)
            assert await worker.once(job_id)
            run, jobs, artifacts = await state(mvp_database, rid)
            assert len(jobs) == 1 and not artifacts and "secret sentinel" not in str(run.state_json)
            if mode == "retry":
                assert jobs[0].status is JobStatus.RUNNING and jobs[0].version == 1
                assert not await worker.once(job_id)
                clock.tick(6)
                executor._model_call = model
                assert await worker.once(job_id)
                _, jobs, artifacts = await state(mvp_database, rid)
                assert len(jobs) == 2 and len(artifacts) == 1
            else:
                assert run.status == ("blocked" if mode == "blocked" else "failed")
                assert jobs[0].status is JobStatus.FAILED
                if mode == "blocked":
                    assert run.state_json["failure"]["blocking_reasons"]
                if mode == "quality":
                    assert run.error == "quality_rejected"
                assert await service.advance(rid) == ()
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


@pytest.mark.parametrize("corrupt", ["plan", "artifact", "routing"])
def test_corrupted_persistence_fails_before_model_call(mvp_database, corrupt):
    async def exercise():
        model = FakeModel(use_parents=True)
        service, clock, rid, owner = await setup(mvp_database, model)
        try:
            node_id = "competitor_analysis"
            if corrupt == "artifact":
                await ModuleGraphWorker(service).once(module_job_id(rid, 1, node_id))
                node_id = "positioning"
            model.calls.clear()
            async with mvp_database() as session, session.begin():
                if corrupt == "plan":
                    row = await session.get(OrchestrationPlanRecord, (rid, 1))
                    row.compiled_plan_json = {**row.compiled_plan_json, "schema_version": "unknown"}
                elif corrupt == "artifact":
                    row = await session.scalar(select(MarketingArtifact).where(MarketingArtifact.run_id == rid))
                    row.payload_json = {**row.payload_json, "execution_result": {}}
                else:
                    row = await session.get(Job, module_job_id(rid, 1, node_id))
                    row.payload_json = {**row.payload_json, "executor_key": "unknown"}
            await ModuleGraphWorker(service).once(module_job_id(rid, 1, node_id))
            run, _, _ = await state(mvp_database, rid)
            assert run.status == "failed" and not model.calls
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_duplicate_start_is_idempotent_and_different_plan_rejected(mvp_database):
    async def exercise():
        service, clock, rid, owner = await setup(mvp_database)
        try:
            plan = compiled(service.executors)
            await asyncio.gather(*(service.start_compiled_run(owner_id=owner, run_id=rid, plan=plan) for _ in range(2)))
            source = source_plan()
            changed = replace(source, nodes=(replace(source.nodes[0], objective="different"), *source.nodes[1:]))
            different = PlanCompiler(ModuleRegistry.load("1.1.0"), service.executors).compile(changed)
            with pytest.raises(StartIdentityConflict):
                await service.start_compiled_run(owner_id=owner, run_id=rid, plan=different)
            _, jobs, _ = await state(mvp_database, rid)
            assert len(jobs) == 1
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_crashes_exhaust_bounded_attempts(mvp_database):
    async def exercise():
        service, clock, rid, owner = await setup(mvp_database)
        try:
            jid = module_job_id(rid, 1, "competitor_analysis")
            for _ in range(3):
                assert await service.claim(jid)
                clock.tick()
            assert await service.claim(jid) is None
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "failed" and jobs[0].error == "attempts_exhausted" and not artifacts
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_concurrent_advance_schedules_missing_ready_node_once(mvp_database):
    async def exercise():
        service, clock, rid, owner = await setup(mvp_database)
        try:
            original = service._advance_locked
            service._advance_locked = AsyncMock(return_value=[])
            await ModuleGraphWorker(service).once(module_job_id(rid, 1, "competitor_analysis"))
            service._advance_locked = original
            _, jobs, artifacts = await state(mvp_database, rid)
            assert len(jobs) == len(artifacts) == 1
            other = GraphExecutionService(mvp_database, executors=registry(), clock=clock)
            results = await asyncio.gather(service.advance(rid), other.advance(rid))
            assert sum(len(r) for r in results) == 1
            _, jobs, _ = await state(mvp_database, rid)
            assert len(jobs) == 2
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_sql_outage_keeps_claim_recoverable_and_completion_is_atomic(mvp_database):
    from sqlalchemy.exc import SQLAlchemyError
    async def exercise():
        service, clock, rid, owner = await setup(mvp_database)
        try:
            original = service._advance_locked
            service._advance_locked = AsyncMock(side_effect=SQLAlchemyError("offline"))
            jid = module_job_id(rid, 1, "competitor_analysis")
            with pytest.raises(SQLAlchemyError):
                await ModuleGraphWorker(service).once(jid)
            run, jobs, artifacts = await state(mvp_database, rid)
            assert jobs[0].status is JobStatus.RUNNING and not artifacts
            async with mvp_database() as session:
                assert (await session.get(JobExecution, jid)).claim_token
            service._advance_locked = original
            clock.tick()
            assert await ModuleGraphWorker(service).once(jid)
            _, jobs, artifacts = await state(mvp_database, rid)
            assert len(jobs) == 2 and len(artifacts) == 1
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_unready_downstream_never_claimed(mvp_database):
    async def exercise():
        service, clock, rid, owner = await setup(mvp_database)
        try:
            assert await service.claim(module_job_id(rid, 1, "positioning")) is None
            await asyncio.gather(service.advance(rid), service.advance(rid))
            _, jobs, artifacts = await state(mvp_database, rid)
            assert len(jobs) == 1 and not artifacts
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())
