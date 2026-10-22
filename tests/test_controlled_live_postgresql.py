"""Real committed attempt admission, graph restart/lease and production controls."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select

from app.llm import controlled_live as live
from app.llm.telemetry import graph_call_context
from app.models import JobExecution, JobStatus, MarketingRun
from app.orchestration_runtime.service import GraphExecutionService
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests.postgresql_support import mvp_database
from tests.test_controlled_live import payload
from tests.test_graph_postgresql import setup, cleanup, state
from tests.graph_fakes import registry, FakeModel


def test_committed_admission_concurrent_calls_and_process_replacement(mvp_database):
    async def exercise():
        async with mvp_database() as session, session.begin():
            await session.execute(delete(MarketingRun).where(MarketingRun.run_id == live.LEDGER_ID))
        try:
            async def reserve(index):
                with live.provider_operation("intent", index):
                    return await live.ControlledLiveAdmission(mvp_database).reserve(payload())
            results = await asyncio.gather(reserve(1), reserve(2), return_exceptions=True)
            receipts = [value for value in results if isinstance(value, tuple)]
            assert len(receipts) == 1
            assert sum(isinstance(value, live.ControlledLiveBlocked) for value in results) == 1
            with pytest.raises(live.ControlledLiveBlocked):
                await reserve(3)  # simulated replacement process sees the committed unknown
            await live.ControlledLiveAdmission(mvp_database).finish(receipts[0], success=True)
            with pytest.raises(live.ControlledLiveBlocked):
                await reserve(1 if isinstance(results[0], tuple) else 2)
            receipt = await reserve(4)
            await live.ControlledLiveAdmission(mvp_database).finish(receipt, success=False)
            with pytest.raises(live.ControlledLiveBlocked):
                await reserve(5)
        finally:
            async with mvp_database() as session, session.begin():
                await session.execute(delete(MarketingRun).where(MarketingRun.run_id == live.LEDGER_ID))
    asyncio.run(exercise())


@pytest.mark.parametrize("controlled", [False, True])
@pytest.mark.parametrize("failure", ["timeout", "crash", "committed"])
def test_graph_timeout_restart_expired_lease_and_committed_replay(mvp_database, controlled, failure):
    async def exercise():
        model = FakeModel(use_parents=True)
        service, clock, rid, owner = await setup(mvp_database, model=model, controlled_live=controlled)
        try:
            _, jobs, _ = await state(mvp_database, rid)
            job_id = jobs[0].job_id
            if failure == "timeout":
                executor = service.executors.resolve("competitor_analysis.v1")
                executor._model_call = AsyncMock(side_effect=TimeoutError())
                assert await ModuleGraphWorker(service).once(job_id)
                executor._model_call.assert_awaited_once()
            elif failure == "crash":
                item = await service.claim(job_id)
                assert await service.load_work(item) is not None
                # External response may have been lost before finish; claim is durable.
            else:
                assert await ModuleGraphWorker(service).once(job_id)
            clock.tick(400)
            replacement_model = FakeModel(use_parents=True)
            replacement = GraphExecutionService(mvp_database, executors=registry(replacement_model),
                clock=clock, controlled_live=controlled)
            worked = await ModuleGraphWorker(replacement).once(job_id)
            run, jobs, artifacts = await state(mvp_database, rid)
            job = next(row for row in jobs if row.job_id == job_id)
            if failure == "committed":
                assert not worked and job.status is JobStatus.SUCCEEDED
                assert len(artifacts) == 1 and replacement_model.calls == []
            elif controlled:
                assert not worked and job.status is JobStatus.FAILED
                assert run.error == "controlled_outcome_unknown"
                assert replacement_model.calls == [] and not artifacts
                async with mvp_database() as session:
                    assert (await session.get(JobExecution, job_id)).attempts == 1
            else:
                assert worked and job.status is JobStatus.SUCCEEDED
                assert len(replacement_model.calls) == 1 and len(artifacts) == 1
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())
