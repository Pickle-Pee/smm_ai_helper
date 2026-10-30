"""Production menu metadata must coexist with master retry governance."""
import asyncio

import pytest

from app.orchestration_runtime.contracts import module_job_id
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.service import GraphExecutionService
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests.postgresql_support import mvp_database
from tests.test_graph_postgresql import setup, cleanup, state
from tests.test_responses_governance_postgresql import provider


@pytest.mark.parametrize("governance", [False, True])
def test_history_title_survives_provider_receipts_and_worker_restart(mvp_database, monkeypatch, governance):
    async def exercise():
        service, clock, rid, owner = await setup(
            mvp_database, production_model_call, responses_governance=governance)
        jid = module_job_id(rid, 1, "competitor_analysis")
        sends = provider(monkeypatch, "timeout")
        try:
            run, _, _ = await state(mvp_database, rid)
            title = run.input_json["history_title"]
            assert title
            assert ("responses_retry" in run.input_json) is governance
            # Idempotent admission must retain the committed policy and title.
            from tests.graph_fakes import compiled
            await service.start_compiled_run(owner_id=owner, run_id=rid, plan=compiled(service.executors))
            assert await ModuleGraphWorker(service).once(jid)
            run, _, _ = await state(mvp_database, rid)
            assert run.input_json["history_title"] == title
            assert len(sends) == 1
            if governance:
                assert run.status == "failed"
                calls = run.input_json["responses_retry"]["calls"]
                assert len(calls) == 1 and calls[0]["outcome"] == "unknown"
                # Disabling enrollment on a replacement worker cannot erase policy.
                replacement = GraphExecutionService(mvp_database, executors=service.executors, clock=clock)
                clock.tick()
                assert not await ModuleGraphWorker(replacement).once(jid)
                assert len(sends) == 1
                run, _, _ = await state(mvp_database, rid)
                assert run.input_json["history_title"] == title
                assert run.input_json["responses_retry"]["calls"] == calls
            else:
                assert "responses_retry" not in run.input_json
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())
