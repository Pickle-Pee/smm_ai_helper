"""Synthetic Little Feet graph through production transport and real acceptance.

The proposals reproduce proven contract gaps, not the unknown historical response.
"""
import asyncio
import copy
import json
import uuid

import httpx
from jsonschema import Draft202012Validator

from app.marketing_orchestrator import PlanningContext
from app.marketing_orchestrator.strategy import SCENARIO
from app.models import JobStatus, User
from app.module_execution import ModuleExecutionRequest, ModuleExecutorDispatcher, UpstreamExecutionResult
from app.orchestration_runtime.contracts import module_job_id
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.serialization import result_from_json
from app.orchestration_runtime.service import GraphExecutionService, evaluate_result
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests.positioning_provider import PositioningProvider
from tests.postgresql_support import mvp_database
from tests.test_graph_model_adapter import install_transport
from tests.test_graph_postgresql import cleanup, state
from tests.test_module_executors import fact
from tests.test_strategy_builder import strategy_compiled, strategy_executors


def little_feet_context():
    # Synthetic owner-confirmed facts; no research URLs, economics or seed claims.
    values = {
        "business_goal": "Grow qualified parent inquiries for Little Feet",
        "product": "Little Feet children's footwear",
        "target_or_target_hypothesis": "Parents choosing children's footwear",
        "product_truth": "Owner confirmed: Little Feet sells children's footwear",
        "existing_proof": "Owner supplied product photographs",
    }
    return PlanningContext(known_facts=tuple(
        fact(key, value, scenario_relevance=frozenset({SCENARIO}))
        for key, value in values.items()))


def statement_objects(schema):
    """Inspect all complete statement branches, including nested support anyOf."""
    if isinstance(schema, dict):
        properties = schema.get("properties", {})
        if {"output_name", "kind", "items", "parent_claim_ids"} <= properties.keys():
            yield properties
        for value in schema.values():
            yield from statement_objects(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from statement_objects(value)


def allowed_values(field):
    return set(field["enum"]) if "enum" in field else {field["const"]}


def assert_cmo_schema(call, accepted_parent_ids):
    data = json.loads(call["input"][1]["content"])
    schema = call["text"]["format"]["schema"]
    assert call["text"]["format"]["strict"] is True
    assert call["max_output_tokens"] == 4000
    assert {u["producer_node_id"] for u in data["upstream_results"]} == {"positioning"}
    assert set(data["allowed_parent_claim_ids"]) == accepted_parent_ids
    assert len(accepted_parent_ids) == 16
    assert schema["$defs"]["AllowedParentClaimId"]["enum"] == sorted(accepted_parent_ids)
    assert schema["$defs"]["AllowedEvidenceId"]["enum"] == sorted(
        e["evidence_id"] for e in data["local_evidence"])
    covered = set()
    for properties in statement_objects(schema):
        names = allowed_values(properties["output_name"])
        covered.update(names)
        assert allowed_values(properties["kind"]) <= {"HYPOTHESIS", "RECOMMENDATION"}
        assert properties["items"]["minItems"] == 1
        assert properties["parent_claim_ids"]["minItems"] >= 1
        parent_items = properties["parent_claim_ids"]["items"]
        if "$ref" in parent_items:
            parent_items = schema["$defs"][parent_items["$ref"].rsplit("/", 1)[-1]]
        assert set(parent_items["enum"]) == accepted_parent_ids
        if "main_growth_constraint" in names:
            assert names == {"main_growth_constraint"}
            assert allowed_values(properties["kind"]) == {"HYPOTHESIS"}
            assert properties["items"]["maxItems"] == 1
        else:
            assert properties["items"]["maxItems"] == 3
    assert covered == set(data["expected_outputs"])


class StrategyContractProvider:
    """Generate a fresh valid response after independently checking proposals."""
    def __init__(self):
        self.positioning = PositioningProvider()
        self.calls = []
        self.rejected_proposals = []

    def __call__(self, request):
        body = json.loads(request.content)
        self.calls.append(body)
        data = json.loads(body["input"][1]["content"])
        if "main_growth_constraint" not in data["expected_outputs"]:
            return self.positioning(request)
        schema = body["text"]["format"]["schema"]
        validator = Draft202012Validator(schema)
        parents = data["allowed_parent_claim_ids"]
        locals = [e["evidence_id"] for e in data["local_evidence"]]
        assert parents and locals
        base = dict(output_name="main_growth_constraint", text="Validate the supplied growth hypothesis",
            kind="HYPOTHESIS", confidence="MEDIUM", items=["Validate demand from supplied parent context"],
            evidence_ids=[], parent_claim_ids=[parents[0]])
        changes = {
            "local_only": dict(evidence_ids=[locals[0]], parent_claim_ids=[]),
            "observation": dict(output_name="strategic_diagnosis", kind="OBSERVATION"),
            "constraint_recommendation": dict(kind="RECOMMENDATION"),
            "two_constraints": dict(items=["Validate demand", "Validate messaging"]),
        }
        for name, change in changes.items():
            proposal = dict(outputs=[{**base, **change}], assumptions=[], limitations=[])
            assert not validator.is_valid(proposal), name
            self.rejected_proposals.append(name)
        # No proposals are sent or repaired: construct the constrained generation.
        payload = dict(outputs=[{**copy.deepcopy(base), "output_name": name}
            for name in data["expected_outputs"]], assumptions=[], limitations=[])
        assert validator.is_valid(payload)
        # Both parent-only and local+parent support remain valid for each output.
        both = copy.deepcopy(payload)
        for statement in both["outputs"]:
            statement["evidence_ids"] = [locals[0]]
        assert validator.is_valid(both)
        return httpx.Response(200, json={"status": "completed", "output_text": json.dumps(payload)})


def assert_positioning_accepted(result, quality):
    assert result.normalized_result.module_status.value == "PASS_WITH_LIMITATIONS"
    assert len(result.normalized_result.claims) == 16
    ids = {c.claim_id for c in result.normalized_result.claims}
    assert set(quality["accepted_claim_ids"]) == ids
    assert quality["accepted_result_ids"] == [result.normalized_result.result_id]
    return ids


def test_little_feet_production_wire_and_accepted_positioning_parents(monkeypatch):
    provider = StrategyContractProvider()
    clients = install_transport(monkeypatch, provider)

    async def exercise():
        executors = strategy_executors(production_model_call)
        plan = strategy_compiled(little_feet_context(), executors)
        assert [n.node_id for n in plan.nodes] == ["positioning", "virtual_cmo", "experiments"]
        dispatcher = ModuleExecutorDispatcher(executors)
        results = []
        for node in plan.nodes[:2]:
            upstream = tuple(UpstreamExecutionResult(producer_node_id="positioning", result=r) for r in results)
            request = ModuleExecutionRequest(execution_id=node.node_id + "_contract", module_id=node.module_id,
                objective=node.objective, expected_outputs=node.expected_outputs,
                context_packet=node.context_packet, upstream_results=upstream)
            result = await dispatcher.dispatch(node.binding, request)
            quality = evaluate_result(request.execution_id, result, upstream)
            if node.node_id == "positioning":
                accepted = assert_positioning_accepted(result, quality)
            else:
                assert result.normalized_result.result_id in quality["accepted_result_ids"]
                assert {c.claim_id for c in result.normalized_result.claims} <= set(quality["accepted_claim_ids"])
                assert result.schema_version == "virtual_cmo.payload.v1"
                assert_cmo_schema(provider.calls[-1], accepted)
            results.append(result)

    asyncio.run(exercise())
    assert len(provider.calls) == 2
    assert len(provider.positioning.calls) == 1
    assert set(provider.rejected_proposals) == {
        "local_only", "observation", "constraint_recommendation", "two_constraints"}
    assert all(client.is_closed for client in clients)


def test_little_feet_graph_persists_cmo_and_releases_experiments(mvp_database, monkeypatch):
    provider = StrategyContractProvider()
    install_transport(monkeypatch, provider)

    async def exercise():
        executors = strategy_executors(production_model_call)
        plan = strategy_compiled(little_feet_context(), executors)
        service = GraphExecutionService(mvp_database, executors=executors)
        rid = uuid.uuid4().hex
        async with mvp_database() as session, session.begin():
            user = User(telegram_id=int(uuid.uuid4().hex[:12], 16))
            session.add(user)
            await session.flush()
            owner = user.id
        try:
            await service.start_compiled_run(owner_id=owner, run_id=rid, plan=plan)
            worker = ModuleGraphWorker(service)
            assert await worker.once(module_job_id(rid, 1, "positioning"))
            _, jobs, artifacts = await state(mvp_database, rid)
            assert {j.workflow_step: j.status for j in jobs} == {
                "positioning": JobStatus.SUCCEEDED, "virtual_cmo": JobStatus.PENDING}
            positioning = artifacts[0].payload_json
            accepted = assert_positioning_accepted(
                result_from_json(positioning["execution_result"]), positioning["quality"])
            assert await worker.once(module_job_id(rid, 1, "virtual_cmo"))
            run, jobs, artifacts = await state(mvp_database, rid)
            assert run.error is None
            assert {j.workflow_step: j.status for j in jobs} == {
                "positioning": JobStatus.SUCCEEDED, "virtual_cmo": JobStatus.SUCCEEDED,
                "experiments": JobStatus.PENDING}
            assert {a.step for a in artifacts} == {"positioning", "virtual_cmo"}
            saved = next(a.payload_json for a in artifacts if a.step == "virtual_cmo")
            cmo = result_from_json(saved["execution_result"])
            assert cmo.normalized_result.result_id in saved["quality"]["accepted_result_ids"]
            assert {c.claim_id for c in cmo.normalized_result.claims} <= set(saved["quality"]["accepted_claim_ids"])
            assert_cmo_schema(provider.calls[-1], accepted)
            # Runnable means the durable scheduler allows a claim and loads work.
            item = await service.claim(module_job_id(rid, 1, "experiments"))
            assert item is not None
            binding, request = await service.load_work(item)
            assert binding.executor_key == "experiments.v1"
            assert "virtual_cmo" in {u.producer_node_id for u in request.upstream_results}
            assert len(provider.calls) == 2 and len(provider.positioning.calls) == 1
        finally:
            await cleanup(mvp_database, rid, owner)

    asyncio.run(exercise())
