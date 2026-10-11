"""Production Responses wire -> dispatcher -> PostgreSQL gates and durable graph."""
import asyncio
import json
import uuid
from dataclasses import replace

import httpx
import pytest
from jsonschema import Draft202012Validator

from app.marketing_copilot.application_contracts import CopilotRequest
from app.marketing_copilot.context_resolver import ContextEntry
from app.marketing_copilot.contracts import IntentKind
from app.marketing_copilot.factory import build_marketing_copilot_service
from app.models import JobStatus, User
from app.orchestration_runtime.composition import build_production_graph_runtime
from app.orchestration_runtime.serialization import result_from_json
from app.module_execution.executors.common import plain
from tests.postgresql_support import mvp_database
from tests.positioning_provider import PositioningProvider
from tests.test_copilot_application import intent_model
from tests.test_graph_model_adapter import install_transport
from tests.test_graph_postgresql import cleanup, state
from tests.test_production_graph_worker import queue
from tests.test_strategy_builder_postgresql import execute_node
from tests.test_virtual_cmo_numeric_grounding import (
    AGE, PRICE, RECOMMENDATION, daycare_facts, grounded_output, enable_module_log,
)


class DaycareProvider:
    def __init__(self, failure):
        self.failure = failure
        self.calls = []
        self.positioning = PositioningProvider()

    def __call__(self, request):
        body = json.loads(request.content)
        self.calls.append(body)
        data = json.loads(body["input"][1]["content"])
        if "main_growth_constraint" not in data["expected_outputs"]:
            return self.positioning(request)
        schema = body["text"]["format"]["schema"]
        outputs = [dict(output_name=name, kind="HYPOTHESIS", confidence="MEDIUM",
            text="Проверить влияние форматов посещения на спрос.", items=["Сопоставить спрос с расходами без прогноза прибыли."],
            evidence_ids=[data["local_evidence"][0]["evidence_id"]],
            parent_claim_ids=data["allowed_parent_claim_ids"][:8], numeric_context=[])
            for name in data["expected_outputs"]]
        payload = dict(outputs=outputs, assumptions=[], limitations=[])
        grounded_output(payload, data)
        if self.failure in ("text", "items"):
            outputs[0][self.failure] = RECOMMENDATION if self.failure == "text" else [RECOMMENDATION]
        elif self.failure == "combination":
            outputs[0]["numeric_context"][1]["quote"] = "Для детей от 2 до 7 лет цена 18 000 рублей."
        assert body["text"]["format"]["strict"] is True
        assert Draft202012Validator(schema).is_valid(payload)
        # Every object in the actual provider wire has all properties required.
        def strict(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    assert set(node["required"]) == set(node["properties"])
                    assert node["additionalProperties"] is False
                for child in node.values():
                    strict(child)
            elif isinstance(node, list):
                for child in node:
                    strict(child)
        strict(schema)
        return httpx.Response(200, json={"status": "completed", "output_text": json.dumps(payload)})


@pytest.mark.parametrize("failure", [None, "text", "items", "combination"])
def test_daycare_production_graph_numeric_grounding(mvp_database, monkeypatch, failure, caplog):
    provider = DaycareProvider(failure)
    install_transport(monkeypatch, provider)
    async def exercise():
        runtime = build_production_graph_runtime(queue=queue(), sessions=mvp_database)
        service = runtime.service
        async with mvp_database() as session, session.begin():
            user = User(telegram_id=int(uuid.uuid4().hex[:12], 16))
            session.add(user)
            await session.flush()
            owner = user.id
        rid = None
        try:
            copilot = build_marketing_copilot_service(intent_model=intent_model(IntentKind.MARKETING_STRATEGY),
                executor_registry=runtime.executors, graph_service=service, registry_version="1.3.0")
            response = await copilot.execute(CopilotRequest(actor_id=owner, request_id=uuid.uuid4().hex,
                message="Разработать стратегию повышения прибыльности детского сада.",
                current_request=tuple(ContextEntry(f.input_key.value if f.input_key else f.label, f)
                    for f in (replace(f, value=plain(f.value), scenario_relevance=frozenset({"strategy_builder_v1"}))
                                                for f in daycare_facts()))))
            rid = response.workflow.run_id
            await execute_node(service, rid, "positioning")
            await execute_node(service, rid, "virtual_cmo")
            run, jobs, artifacts = await state(mvp_database, rid)
            cmo = next(j for j in jobs if j.workflow_step == "virtual_cmo")
            assert len(provider.calls) == 2  # One provider call for each required node.
            if failure:
                assert run.status == "failed"
                assert cmo.status is JobStatus.FAILED
                assert not any(a.step == "virtual_cmo" for a in artifacts)
                assert not any(j.workflow_step == "experiments" for j in jobs)
                assert "rule=numerical_support_required field=" + (
                    "numeric_context" if failure == "combination" else failure) in caplog.text
                assert RECOMMENDATION not in caplog.text
                # Poll/advance cannot turn a semantic rejection into a retry.
                assert await service.advance(rid) == ()
                assert len(provider.calls) == 2
            else:
                assert cmo.status is JobStatus.SUCCEEDED
                assert next(j for j in jobs if j.workflow_step == "experiments").status is JobStatus.PENDING
                artifact = next(a for a in artifacts if a.step == "virtual_cmo")
                result = result_from_json(artifact.payload_json["execution_result"])
                assert [c["quote"] for c in json.loads(result.normalized_result.claims[0].value)["numeric_context"]] == [AGE, PRICE]
                quality = artifact.payload_json["quality"]
                assert result.normalized_result.result_id in quality["accepted_result_ids"]
                assert all(c.claim_id in quality["accepted_claim_ids"] for c in result.normalized_result.claims)
                # Durable reload through a fresh service retains exactly gated quotes.
                fresh = build_production_graph_runtime(queue=queue(), sessions=mvp_database).service
                from app.orchestration_runtime.contracts import module_job_id
                item = await fresh.claim(module_job_id(rid, 1, "experiments"))
                _, request = await fresh.load_work(item)
                saved = next(u.result for u in request.upstream_results if u.result.module_id.value == "VIRTUAL_CMO")
                assert saved == result
        finally:
            if rid:
                await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())
