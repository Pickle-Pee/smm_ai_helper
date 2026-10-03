"""Issue #77: production wire contract, safe diagnostics and application advance."""
import asyncio
import json
import traceback
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.marketing_copilot.contracts import IntentKind
from app.marketing_copilot.application_contracts import ResultKind
from app.marketing_copilot.factory import build_marketing_copilot_service
from app.marketing_copilot.provider_adapters import application_model_call
from app.module_execution import ModuleExecutionRequest
from app.module_execution.acceptance import fully_accepted
from app.module_execution.executors import PositioningExecutor, ExecutorOutputError
from app.module_execution.executors.common import OutputFailureStage
from app.module_execution.executors.schemas import OutputStatement, PositioningOutput
from app.module_registry import ModuleId, ModuleRegistry
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.contracts import module_job_id
from app.orchestration_runtime.service import GraphExecutionService
from app.orchestration_runtime.worker import ModuleGraphWorker, transient
from tests.positioning_provider import ROWS, PositioningProvider, allowed_kinds
from tests.test_graph_model_adapter import install_transport
from tests.test_module_executors import request, FakeModel, dispatch
from tests.test_copilot_application import (
    entries, intent_model, run, POSITIONING_MESSAGE, POSITIONING_FACTS,
)
from tests.test_strategy_builder import strategy_compiled, strategy_executors


@pytest.fixture(params=[False, True], ids=["logger-enabled", "logger-disabled"])
def rejection_log(monkeypatch, request):
    from app.module_execution.executors.common import log

    # Alembic fileConfig disables existing loggers in migration tests. Observe
    # the executor's logging contract even after that global reconfiguration.
    monkeypatch.setattr(log, "disabled", request.param)
    warning = Mock()
    monkeypatch.setattr(log, "warning", warning)
    return warning


def assert_safe_rejection_log(warning, stage):
    warning.assert_called_once_with(
        "Module output rejected module=%s stage=%s", "POSITIONING", stage)


def test_minimal_live_failure_class_is_structurally_excluded():
    # This was strict-valid under the old OutputStatement kind contract, but
    # validate_statement rejected it. Synthetic text/support, never a live dump.
    statement = OutputStatement(output_name="USP_directions", text="Test direction",
        kind="RECOMMENDATION", confidence="MEDIUM", evidence_ids=["evd_test"], parent_claim_ids=[])
    with pytest.raises(ValueError, match="Differentiation requires hypothesis"):
        PositioningExecutor(model_call=None).validate_statement(statement, {}, {})
    schema = PositioningOutput.model_json_schema()
    for name in ("differentiation", "points_of_difference", "USP_directions"):
        assert allowed_kinds(schema, name) == {"HYPOTHESIS"}
    assert "RECOMMENDATION" in allowed_kinds(schema, "offer")


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0", "1.2.0"])
def test_literal_registry_schema_fixture_and_planner_output_parity(version):
    expected = ModuleRegistry.load(version).get(ModuleId.POSITIONING).outputs
    assert tuple(row[0] for row in ROWS) == expected
    schema = PositioningOutput.model_json_schema()
    names = set()
    for variant in schema["properties"]["outputs"]["items"]["anyOf"]:
        definition = schema["$defs"][variant["$ref"].rsplit("/", 1)[-1]]
        names.update(definition["properties"]["output_name"]["enum"])
        assert definition["additionalProperties"] is False
        assert set(definition["required"]) == set(definition["properties"])
    assert names == set(expected)
    assert strategy_compiled().nodes[0].expected_outputs == expected


def test_complete_positioning_through_production_http_adapter(monkeypatch):
    provider = PositioningProvider()
    install_transport(monkeypatch, provider)
    invocation = request(ModuleId.POSITIONING)
    output = asyncio.run(PositioningExecutor(model_call=production_model_call).execute(invocation))
    assert output.normalized_result.module_status.value == "PASS_WITH_LIMITATIONS"
    assert [s["output_name"] for s in output.payload["outputs"]] == list(invocation.expected_outputs)
    assert len(provider.calls) == 1 and provider.calls[0]["max_output_tokens"] == 4000
    data = json.loads(provider.calls[0]["input"][1]["content"])
    proof = {e["evidence_id"] for e in data["local_evidence"] if e["input_key"] in {"product_truth", "existing_proof"}}
    for statement, claim in zip(output.payload["outputs"], output.normalized_result.claims):
        assert statement["evidence_ids"] == claim.evidence_ids
        if statement["output_name"] in {"differentiation", "points_of_difference", "USP_directions"}:
            assert statement["kind"] == "HYPOTHESIS"
        if statement["output_name"] in {"RTB", "value_proposition", "positioning_statement", "offer"}:
            assert proof.intersection(statement["evidence_ids"])


@pytest.mark.parametrize("projected", [False, True])
def test_direct_copilot_module_result_with_production_provider_and_context_projection(monkeypatch, projected):
    provider = PositioningProvider()
    install_transport(monkeypatch, provider)
    svc = build_marketing_copilot_service(
        intent_model=intent_model(IntentKind.POSITIONING, facts=POSITIONING_FACTS if projected else None),
        module_model=application_model_call, registry_version="1.2.0")
    result = run(svc, POSITIONING_MESSAGE,
        current_request=() if projected else entries(ModuleId.POSITIONING))
    assert result.kind is ResultKind.MODULE_RESULT
    assert len(result.module_result.normalized_result.claims) == 16
    assert len(provider.calls) == 1


def test_strategy_first_node_passes_worker_quality_and_unlocks_cmo(monkeypatch):
    provider = PositioningProvider()
    install_transport(monkeypatch, provider)
    executors = strategy_executors(production_model_call)
    plan = strategy_compiled(executors=executors)
    node, cmo = plan.nodes[:2]
    job_id = module_job_id("a" * 64, 1, node.node_id)
    invocation = ModuleExecutionRequest(execution_id=job_id, module_id=node.module_id,
        objective=node.objective, expected_outputs=node.expected_outputs, context_packet=node.context_packet)
    item = SimpleNamespace(run_id="a" * 64, job_id=job_id, node_id=node.node_id)
    service = SimpleNamespace(executors=executors, lease_seconds=330, claim=AsyncMock(return_value=item),
        load_work=AsyncMock(return_value=(node.binding, invocation)), fail=AsyncMock(), finish=AsyncMock(return_value=True))
    assert not GraphExecutionService._ready(plan, cmo, {}, {})
    assert asyncio.run(ModuleGraphWorker(service).once())
    service.fail.assert_not_awaited()
    service.finish.assert_awaited_once()
    _, result, quality = service.finish.call_args.args
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])
    assert GraphExecutionService._ready(plan, cmo, {}, {node.node_id: result})
    assert len(provider.calls) == 1


@pytest.mark.parametrize("mutation,stage", [
    (lambda p,d: p.update(private="PRIVATE_SENTINEL"), "schema_invalid"),
    (lambda p,d: p["outputs"].pop(), "output_coverage_invalid"),
    (lambda p,d: p["outputs"].append(p["outputs"][0].copy()), "output_coverage_invalid"),
    (lambda p,d: p["outputs"][0].update(evidence_ids=["evd_unknown"]), "evidence_reference_invalid"),
    (lambda p,d: p["outputs"][0].update(parent_claim_ids=["clm_unknown"]), "parent_reference_invalid"),
    (lambda p,d: p["outputs"][0].update(evidence_ids=[], parent_claim_ids=[]), "support_missing"),
    (lambda p,d: p["outputs"][0]["evidence_ids"].append(p["outputs"][0]["evidence_ids"][0]), "support_identity_invalid"),
    (lambda p,d: p["outputs"][0].update(parent_claim_ids=["clm_unknown", "clm_unknown"]), "support_identity_invalid"),
    (lambda p,d: next(s for s in p["outputs"] if s["output_name"] == "USP_directions").update(kind="RECOMMENDATION"), "schema_invalid"),
])
def test_safe_failure_stages_fail_closed_without_retry(monkeypatch, rejection_log, mutation, stage):
    provider = PositioningProvider(mutation)
    install_transport(monkeypatch, provider)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(PositioningExecutor(model_call=production_model_call).execute(request(ModuleId.POSITIONING)))
    assert caught.value.stage.value == stage
    assert not transient(caught.value)
    assert len(provider.calls) == 1
    assert_safe_rejection_log(rejection_log, stage)
    assert "PRIVATE_SENTINEL" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("name", ["RTB", "value_proposition", "positioning_statement", "offer"])
@pytest.mark.parametrize("input_key,valid", [("product_truth", True), ("existing_proof", True), ("target_or_target_hypothesis", False)])
def test_product_claim_support_remains_required(name, input_key, valid):
    from tests.test_module_executors import fact, facts_for_module
    def support(payload, data):
        payload["outputs"][0]["evidence_ids"] = [next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"] == input_key)]
    invocation = request(ModuleId.POSITIONING, outputs=(name,),
        facts=(*facts_for_module(ModuleId.POSITIONING), fact("existing_proof")))
    if valid:
        assert dispatch(invocation, FakeModel(support)).normalized_result.claims
    else:
        with pytest.raises(ExecutorOutputError) as caught:
            dispatch(invocation, FakeModel(support))
        assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


@pytest.mark.parametrize("raw,stage", [("not JSON PRIVATE_SENTINEL", "json_invalid"), ("{}", "schema_invalid")])
def test_parse_diagnostics_are_safe(raw, stage, rejection_log):
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(request(ModuleId.POSITIONING), AsyncMock(return_value=raw))
    assert caught.value.stage.value == stage
    assert_safe_rejection_log(rejection_log, stage)
    assert "PRIVATE_SENTINEL" not in "".join(traceback.format_exception(caught.value))


def test_result_construction_diagnostics_are_safe(monkeypatch, rejection_log):
    import app.module_execution.executors.common as common
    def invalid(**kwargs):
        raise ValueError("PRIVATE_SENTINEL")
    monkeypatch.setattr(common, "NormalizedClaim", invalid)
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(request(ModuleId.POSITIONING))
    assert caught.value.stage is OutputFailureStage.RESULT_CONTRACT_INVALID
    assert_safe_rejection_log(rejection_log, "result_contract_invalid")
    assert "PRIVATE_SENTINEL" not in "".join(traceback.format_exception(caught.value))
