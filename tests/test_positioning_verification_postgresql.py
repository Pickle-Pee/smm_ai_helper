"""Durable verification receipts over real PostgreSQL and mocked HTTP."""
import asyncio

import httpx
import pytest

from app.llm.telemetry import graph_call_context
from app.models import PositioningVerification
from app.module_execution import ModuleExecutorDispatcher
from app.orchestration_runtime.errors import RuntimeContractError
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.retry_policy import RetryGovernanceError
from app.orchestration_runtime.service import GraphExecutionService, evaluate_result
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests.postgresql_support import mvp_database
from tests.test_graph_model_adapter import install_transport
from tests.test_graph_postgresql import cleanup, setup, state


@pytest.mark.parametrize("crash_after", ["generation", "verification"])
def test_checkpoint_replays_paid_response_without_reposting(mvp_database, monkeypatch, crash_after):
    posts = []

    def respond(request):
        posts.append(request)
        return httpx.Response(200, json={"status": "completed", "output_text": "{}"})

    install_transport(monkeypatch, respond)

    async def provider(service, item, request, *, verification=False):
        hooks = await service.provider_hooks(item, verification=verification)
        with graph_call_context(item, request, None, hooks):
            return await production_model_call(
                instruction="Verify" if verification else "Generate", text="Synthetic test",
                response_schema={"type": "object", "additionalProperties": False, "properties": {}, "required": []},
            )

    async def exercise():
        db = mvp_database
        service, clock, run_id, owner = await setup(
            db, responses_governance=True, positioning_verifier=production_model_call,
        )
        try:
            assert await ModuleGraphWorker(service).once()  # prerequisite competitor job
            item = await service.claim()
            binding, request = await service.load_work(item)
            assert request.module_id.value == "POSITIONING"
            result = await ModuleExecutorDispatcher(service.executors).dispatch(binding, request)
            quality = evaluate_result(item.job_id, result, request.upstream_results)
            assert await provider(service, item, request) == "{}"

            async def restart(old):
                clock.tick()
                replacement = GraphExecutionService(db, executors=service.executors, clock=clock,
                    responses_governance=True, positioning_verifier=production_model_call)
                current = await replacement.claim(old.job_id)
                assert current and current.claim_token != old.claim_token
                with pytest.raises(RetryGovernanceError, match="inactive_graph_attempt"):
                    await replacement.provider_hooks(old)
                return replacement, current

            if crash_after == "generation":
                service, item = await restart(item)
            assert await provider(service, item, request) == "{}"
            assert len(posts) == 1
            assert await service.verification_draft(item, result, {})
            with pytest.raises(RuntimeContractError, match="no verified draft"):
                await service.finish(item, result, quality)
            _, _, artifacts = await state(db, run_id)
            assert all(artifact.step != item.node_id for artifact in artifacts)
            assert await provider(service, item, request, verification=True) == "{}"
            if crash_after == "verification":
                service, item = await restart(item)
                assert await service.verification_draft(item, result, {})
            assert await provider(service, item, request, verification=True) == "{}"
            assert len(posts) == 2
            await service.record_verification(item, {"status": "verified", "assessment": "APPROVE"})
            assert await service.finish(item, result, quality)
            run, _, artifacts = await state(db, run_id)
            assert len([artifact for artifact in artifacts if artifact.step == item.node_id]) == 1
            calls = run.input_json["responses_retry"]["calls"]
            assert [call.get("operation") for call in calls] == [None, "positioning_verification.v1"]
            async with db() as session:
                checkpoint = await session.get(PositioningVerification, item.job_id)
                assert checkpoint.state == "verified"
                assert checkpoint.checkpoint["draft_fingerprint"]
            assert await service.claim(item.job_id) is None
        finally:
            await cleanup(db, run_id, owner)

    asyncio.run(exercise())
