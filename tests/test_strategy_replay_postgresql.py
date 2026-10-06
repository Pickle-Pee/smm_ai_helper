"""Frozen Registry 1.2 plans survive worker recreation with the 1.3 inventory."""
import asyncio
import json
from pathlib import Path
import uuid

from app.models import JobStatus, OrchestrationPlanRecord, User
from app.orchestration_runtime.contracts import module_job_id
from app.orchestration_runtime.serialization import plan_from_json
from app.orchestration_runtime.service import GraphExecutionService
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests.postgresql_support import mvp_database
from tests.test_graph_postgresql import Clock, cleanup, state
from tests.test_strategy_registry_compatibility import executors


def test_frozen_legacy_strategy_loads_and_executes_after_worker_recreation(mvp_database):
    raw = json.loads((Path(__file__).parent / "fixtures/strategy_registry_v1_2.json").read_text(encoding="utf-8"))
    plan = plan_from_json(raw)
    assert plan.registry_version == "1.2.0"
    assert plan.execution_fingerprint == "97e10b3f1741995fbfee4002304df2cf5e1b44989683398db649f0b3b0d97b7f"

    async def exercise():
        rid = "legacy-strategy-" + uuid.uuid4().hex
        clock = Clock()
        async with mvp_database() as session, session.begin():
            user = User(telegram_id=int(uuid.uuid4().hex[:12], 16))
            session.add(user)
            await session.flush()
            owner = user.id
        try:
            await GraphExecutionService(mvp_database, executors=executors(), clock=clock).start_compiled_run(
                owner_id=owner, run_id=rid, plan=plan)
            # No compiler or planning state is passed into the recreated worker.
            service = GraphExecutionService(mvp_database, executors=executors(), clock=clock)
            worker = ModuleGraphWorker(service)
            for node in ("positioning", "virtual_cmo", "experiments"):
                assert await worker.once(module_job_id(rid, 1, node))
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.status == "completed", [(j.workflow_step, j.status, j.error) for j in jobs]
            assert all(j.status is JobStatus.SUCCEEDED for j in jobs)
            assert {a.step for a in artifacts} == {"positioning", "virtual_cmo", "experiments"}
            async with mvp_database() as session:
                saved = await session.get(OrchestrationPlanRecord, (rid, 1))
                assert saved.registry_version == "1.2.0"
                assert saved.compiled_plan_json == raw
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())
