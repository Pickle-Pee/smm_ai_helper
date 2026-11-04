"""Durable verification receipts over real PostgreSQL and mocked HTTP."""
import asyncio

import httpx
import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.llm.telemetry import graph_call_context
from app.models import PositioningVerification
from app.module_execution import ModuleExecutorDispatcher
from app.orchestration_runtime.errors import RuntimeContractError
from app.orchestration_runtime.contracts import module_job_id
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.retry_policy import RetryGovernanceError
from app.orchestration_runtime.service import GraphExecutionService, evaluate_result
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests.postgresql_support import mvp_database
from tests.test_graph_model_adapter import install_transport
from tests.test_graph_postgresql import cleanup, setup, state
from tests.test_responses_governance_postgresql import fault


@pytest.mark.parametrize("crash_after", ["generation", "verification", "verification_before_receipt"])
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
            assert await ModuleGraphWorker(service).once(module_job_id(run_id, 1, "competitor_analysis"))
            item = await service.claim(module_job_id(run_id, 1, "positioning"))
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
            if crash_after == "verification_before_receipt":
                async with fault(db, run_id, "receipt"):
                    with pytest.raises(SQLAlchemyError):
                        await provider(service, item, request, verification=True)
                service, item = await restart(item)
                assert await service.verification_draft(item, result, {})
                with pytest.raises(RetryGovernanceError, match="previous_outcome"):
                    await provider(service, item, request, verification=True)
                assert len(posts) == 2
                await service.fail(item, code="execution_invalid")
                _, _, artifacts = await state(db, run_id)
                assert all(artifact.step != item.node_id for artifact in artifacts)
                async with db() as session:
                    checkpoint = await session.get(PositioningVerification, item.job_id)
                    assert checkpoint.state == "blocked"
                    assert "verification" not in checkpoint.checkpoint
                return
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


@pytest.mark.parametrize("assessment", ["APPROVE", "REJECT"])
def test_worker_publishes_only_after_separate_review(mvp_database, monkeypatch, assessment):
    import json

    from tests.test_module_executors import FakeModel

    model = FakeModel(use_parents=True)
    calls = []

    async def respond(request):
        payload = json.loads(request.content)
        schema = payload["text"]["format"]["schema"]
        data = json.loads(payload["input"][1]["content"])
        if "assessment" not in schema["properties"]:
            calls.append("draft")
            output = await model(text=payload["input"][1]["content"], response_schema=schema)
            if "RTB" in data["expected_outputs"]:
                from app.module_execution.executors.positioning_strategy import STRATEGY_OPTIONS

                parsed = json.loads(output)
                truth = next(item for item in data["local_evidence"] if item["input_key"] == "product_truth")
                for row in parsed["outputs"]:
                    if row["output_name"] not in {"RTB", "offer"}:
                        choice = data["positioning_strategy_choices"][row["output_name"]][0]
                        row["text"] = choice["text"]
                        row["evidence_ids"] = list(dict.fromkeys((*choice["required_source_ids"], truth["evidence_id"])))
                    elif row["output_name"] == "offer":
                        row["text"] = truth["value"]
                        row["evidence_ids"] = [truth["evidence_id"]]
                    else:
                        row["text"] = truth["value"]
                        row["evidence_ids"] = [truth["evidence_id"]]
                output = json.dumps(parsed)
        else:
            calls.append("review")
            reviews = {}
            for name, row in data["outputs"].items():
                rtb = name in {"RTB", "offer"}
                text = row["spans"]["whole"]
                support = [
                    identity for identity, source in row["evidence"].items()
                    if rtb and source["role"] in {"product_truth", "demonstration"} and source["text"] == text
                ]
                reviews[name] = {"atoms_complete": True, "output_fulfilled": True, "claims": [{
                    "span_id": "whole", "category": "product" if rtb else "strategy",
                    "kind": "fact" if rtb else "hypothesis", "status": "SUPPORTED" if rtb else "HYPOTHESIS",
                    "support_ids": support,
                }]}
            output = json.dumps({"draft_fingerprint": data["draft_fingerprint"], "assessment": assessment, "reviews": reviews})
        return httpx.Response(200, json={"status": "completed", "output_text": output})

    install_transport(monkeypatch, respond)

    async def exercise():
        db = mvp_database
        service, _, run_id, owner = await setup(db, model=production_model_call,
            responses_governance=True, positioning_verifier=production_model_call)
        try:
            worker = ModuleGraphWorker(service)
            assert await worker.once(module_job_id(run_id, 1, "competitor_analysis"))
            assert await worker.once(module_job_id(run_id, 1, "positioning"))
            run, jobs, artifacts = await state(db, run_id)
            position = next(job for job in jobs if job.workflow_step == "positioning")
            async with db() as session:
                checkpoint = await session.get(PositioningVerification, position.job_id)
                assert checkpoint.state == ("verified" if assessment == "APPROVE" else "rejected"), checkpoint.checkpoint.get("decision")
            assert calls == ["draft", "draft", "review"]
            assert any(row.step == "positioning" for row in artifacts) == (assessment == "APPROVE")
            assert run.status.startswith("completed") == (assessment == "APPROVE")
        finally:
            await cleanup(db, run_id, owner)

    asyncio.run(exercise())
