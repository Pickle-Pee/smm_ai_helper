"""A malicious approval cannot publish contradictory fulfillment promises."""
import asyncio
from dataclasses import replace
import json

import httpx

from app.models import PositioningVerification
from app.orchestration_runtime.contracts import module_job_id
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests import graph_fakes
from tests.postgresql_support import mvp_database
from tests.test_graph_model_adapter import install_transport
from tests.test_graph_postgresql import cleanup, setup, state
from tests.test_module_executors import FakeModel


def test_worker_blocks_fulfillment_contradiction_despite_approve(mvp_database, monkeypatch):
    truth = "Материалы и обжиг включены. Участники забирают изделия после обжига в другой день."
    promise = "Никаких дальнейших действий не потребуется."
    original_plan = graph_fakes.source_plan

    def source_plan(*args, **kwargs):
        plan = original_plan(*args, **kwargs)
        return replace(plan, nodes=tuple(replace(node, context_packet=replace(
            node.context_packet, known_facts=tuple(
                replace(fact, value=truth) if fact.input_key and fact.input_key.value == "product_truth" else fact
                for fact in node.context_packet.known_facts
            ),
        )) for node in plan.nodes))

    monkeypatch.setattr(graph_fakes, "source_plan", source_plan)

    def draft(payload, data):
        if "offer" in data["expected_outputs"]:
            for row in payload["outputs"]:
                if row["output_name"] == "offer":
                    row.update(text=promise, kind="RECOMMENDATION")
                elif row["output_name"] != "RTB":
                    row["text"] = "Test whether beginners value knowing what to practice next."

    model = FakeModel(draft, use_parents=True)
    calls = []

    async def respond(request):
        payload = json.loads(request.content)
        schema = payload["text"]["format"]["schema"]
        data = json.loads(payload["input"][1]["content"])
        if "assessment" not in schema["properties"]:
            calls.append("generation")
            output = await model(text=payload["input"][1]["content"], response_schema=schema)
        else:
            calls.append("verification")
            reviews = {}
            for name, row in data["outputs"].items():
                text = row["spans"]["whole"]
                rtb = name == "RTB"
                ids = [identity for identity, evidence in row["evidence"].items()
                       if rtb and evidence["role"] == "product_truth" and evidence["text"] == text]
                if name == "offer":
                    assert text == promise
                    assert any(evidence.get("requires_follow_up") is True for evidence in row["evidence"].values())
                reviews[name] = {"atoms_complete": True, "output_fulfilled": True, "claims": [{
                    "span_id": "whole",
                    "category": "product" if rtb else "strategy", "kind": "fact" if rtb else "hypothesis",
                    "status": "SUPPORTED" if rtb else "HYPOTHESIS", "support_ids": ids,
                }]}
            output = json.dumps({"draft_fingerprint": data["draft_fingerprint"],
                                 "assessment": "APPROVE", "reviews": reviews})
        return httpx.Response(200, json={"status": "completed", "output_text": output})

    install_transport(monkeypatch, respond)

    async def exercise():
        service, _, run_id, owner = await setup(mvp_database, model=production_model_call,
            responses_governance=True, positioning_verifier=production_model_call)
        try:
            worker = ModuleGraphWorker(service)
            assert await worker.once(module_job_id(run_id, 1, "competitor_analysis"))
            assert await worker.once(module_job_id(run_id, 1, "positioning"))
            run, jobs, artifacts = await state(mvp_database, run_id)
            position = next(job for job in jobs if job.workflow_step == "positioning")
            async with mvp_database() as session:
                checkpoint = await session.get(PositioningVerification, position.job_id)
                assert checkpoint.state == "rejected", checkpoint.checkpoint
                decision = checkpoint.checkpoint["decision"]
                assert decision["assessment"] == "APPROVE"
                assert any(finding["status"] == "CONTRADICTED" and finding["reason"] == "required_follow_up"
                           for finding in decision["findings"])
                assert checkpoint.checkpoint["generation"]["text"]
                assert checkpoint.checkpoint["verification"]["text"]
            assert calls == ["generation", "generation", "verification"]
            assert not any(artifact.step == "positioning" for artifact in artifacts)
            assert run.error == "quality_rejected"
        finally:
            await cleanup(mvp_database, run_id, owner)

    asyncio.run(exercise())
