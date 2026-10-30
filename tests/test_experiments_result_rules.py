"""Closed rejection rules through the actual executor and offline HTTP adapter."""
import asyncio
import ast
from copy import deepcopy
import hashlib
import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from jsonschema import Draft202012Validator

from app.config import settings
from app.module_execution.executors import common, experiments
from app.module_execution.executors.common import (
    ExecutorOutputError, OutputFailureStage, ResultContractError, ResultFailureRule,
)
from app.module_execution.executors.experiments import ExperimentsExecutor
from app.module_execution.executors.intelligence_schemas import ExperimentsOutput
from app.module_execution.executors.provider_schema import schema_measurement, collapse_redundant_support_anyof, collapse_single_support_anyof
from app.module_execution.executors.schema_annotations import strip_schema_annotations
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.worker import transient
from tests.experiments_provider import ExperimentsProvider, with_nonstrategic_parent
from tests.test_experiments_diagnostics import restored
from tests.test_graph_model_adapter import install_transport
from tools import experiments_diagnostics


@pytest.fixture(scope="module")
def invocation():
    return with_nonstrategic_parent(restored())


CASES = [
    ("output_missing_strategic_parent", lambda p: p["outputs"][2].update(parent_claim_ids=["clm_z_additional_recommendation"]), 2, None),
    ("experiment_invalid_strategic_references", lambda p: p["experiments"][1].update(related_strategic_claim_ids=["clm_private_unknown"]), None, 1),
    ("experiment_duplicate_strategic_references", lambda p: p["experiments"][1].update(related_strategic_claim_ids=p["experiments"][1]["related_strategic_claim_ids"][:1] * 2), None, 1),
    ("experiment_constraints_mismatch", lambda p: p["experiments"][1].update(time_resource_constraints=["PRIVATE_CONSTRAINT"]), None, 1),
    ("output_duplicate_names", lambda p: p["outputs"][2].update(output_name=p["outputs"][1]["output_name"]), 2, None),
    ("output_invalid_kind", lambda p: p["outputs"][2].update(kind="INFERENCE"), 2, None),
]


def provider_for(invocation, mutate):
    baseline = asyncio.run(experiments_diagnostics.capture_request(invocation))
    evidence_id = json.loads(baseline.arguments["text"])["local_evidence"][0]["evidence_id"]
    def apply(payload):
        # Keep the support OR valid so the strategic-parent server check runs.
        payload["outputs"][2]["evidence_ids"] = [evidence_id]
        mutate(payload)
    return ExperimentsProvider(apply)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("rule,mutate,oi,ei", CASES)
def test_exact_trigger_safe_error_log_and_unchanged_wire(monkeypatch, caplog, invocation, enabled, rule, mutate, oi, ei):
    baseline = asyncio.run(experiments_diagnostics.capture_request(invocation))
    monkeypatch.setattr(settings, "DEFAULT_TEXT_MODEL_HARD", "gpt-5-mini")
    provider = provider_for(invocation, mutate)
    wire_bytes = []
    def observe(request):
        wire_bytes.append(request.content)
        return provider(request)
    clients = install_transport(monkeypatch, observe)
    monkeypatch.setattr(common.log, "disabled", False)
    with caplog.at_level(logging.WARNING), pytest.raises(ResultContractError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=production_model_call,
            provider_schema_projection=enabled).execute(invocation))
    error = caught.value
    assert error.failure_rule.value == rule
    assert (error.output_index, error.experiment_index) == (oi, ei)
    assert error.stage.value == ("statement_semantics_invalid" if rule == "output_invalid_kind" else "result_contract_invalid")
    assert not transient(error) and error.__suppress_context__ and error.__cause__ is None
    assert str(error) == "Invalid structured module output"
    expected = deepcopy(baseline.payload)
    if enabled:
        expected["text"]["format"]["schema"] = strip_schema_annotations(collapse_single_support_anyof(collapse_redundant_support_anyof(baseline.arguments["response_schema"])))[0]
    assert provider.calls == [expected] and all(c.is_closed for c in clients)
    assert wire_bytes == [httpx.Request("POST", "https://offline.test/responses", json=expected).content]
    rejection = [r for r in caplog.records if r.getMessage().startswith("Module output rejected")]
    assert len(rejection) == 1 and f"failure_rule={rule}" in rejection[0].getMessage()
    assert rejection[0].exc_info is None
    for secret in ("PRIVATE_CONSTRAINT", "clm_", "evd_", "Проверяемое", invocation.execution_id):
        assert secret not in rejection[0].getMessage() and secret not in str(error)


@pytest.mark.parametrize("site", ["NormalizedClaim", "NormalizedModuleResult", "ModuleExecutionResult", "AssumptionRecord", "LimitationRecord", "replace"])
def test_actual_normalization_boundary(monkeypatch, invocation, site):
    target = experiments if site == "replace" else common
    def reject(*args, **kwargs):
        raise ValueError("PRIVATE_MODEL_TEXT clm_private evd_private")
    monkeypatch.setattr(target, site, reject)
    install_transport(monkeypatch, ExperimentsProvider())
    with pytest.raises(ResultContractError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=production_model_call).execute(invocation))
    assert caught.value.failure_rule is ResultFailureRule.RESULT_NORMALIZATION_INVALID
    assert str(caught.value) == "Invalid structured module output"


def test_post_mutation_real_pydantic_failure(monkeypatch, invocation):
    from dataclasses import replace
    # Every initial array is within its bound. The real experiment-parent union
    # adds a thirty-third distinct reference, then Pydantic rejects the mutation.
    upstream = next(u for u in invocation.upstream_results if u.module_id.value == "VIRTUAL_CMO")
    parent = next(c for c in upstream.result.normalized_result.claims if c.claim_type.value == "HYPOTHESIS")
    clones = tuple(replace(parent, claim_id=f"clm_union_{i}") for i in range(33))
    expanded = replace(upstream, result=replace(upstream.result, payload=common.plain(upstream.result.payload),
        normalized_result=replace(upstream.result.normalized_result, claims=clones)))
    request = replace(invocation, upstream_results=tuple(
        expanded if u is upstream else u for u in invocation.upstream_results))
    def mutate(payload):
        for statement in payload["outputs"]:
            statement["parent_claim_ids"] = [c.claim_id for c in clones[:32]]
        for design in payload["experiments"]:
            design["related_strategic_claim_ids"] = [clones[-1].claim_id]
    provider = ExperimentsProvider(mutate)
    install_transport(monkeypatch, provider)
    with pytest.raises(ResultContractError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=production_model_call).execute(request))
    assert caught.value.failure_rule is ResultFailureRule.POST_MUTATION_PYDANTIC_INVALID
    assert len(provider.calls) == 1


def test_unknown_build_failure_uses_closed_fallback(monkeypatch, invocation):
    def reject(*args):
        raise ValueError("PRIVATE_MODEL_TEXT")
    monkeypatch.setattr(ExperimentsExecutor, "build_result", reject)
    install_transport(monkeypatch, ExperimentsProvider())
    with pytest.raises(ResultContractError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=production_model_call).execute(invocation))
    assert caught.value.failure_rule is ResultFailureRule.OTHER_RESULT_CONTRACT_INVALID
    assert caught.value.output_index is caught.value.experiment_index is None


@pytest.mark.parametrize("value", ["PRIVATE_MODEL_TEXT", None, 1])
def test_rule_allowlist(value):
    with pytest.raises(TypeError, match="^Expected server result rule$"):
        ResultContractError(value)


@pytest.mark.parametrize("value", [True, -1, "clm_private", 1.5])
def test_index_allowlist(value):
    with pytest.raises(TypeError, match="^Expected nonnegative server index$"):
        ResultContractError(ResultFailureRule.OUTPUT_INVALID_KIND, output_index=value)


@pytest.mark.parametrize("mutate,stage", [
    (lambda p: p["outputs"][0].update(evidence_ids=["evd_private"]), "schema_invalid"),
    (lambda p: p["outputs"][0].update(text="Guaranteed 90% uplift"), "statement_semantics_invalid"),
    (lambda p: p["experiments"][0].update(expected_signal="Guaranteed 90% uplift"), "statement_semantics_invalid"),
    (lambda p: p["outputs"].pop(), "output_coverage_invalid"),
])
def test_existing_checks_keep_stage_without_invented_rule(monkeypatch, invocation, mutate, stage):
    provider = provider_for(invocation, mutate)
    install_transport(monkeypatch, provider)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=production_model_call).execute(invocation))
    assert caught.value.stage.value == stage and len(provider.calls) == 1
    assert not hasattr(caught.value, "failure_rule")


def run_recipe(monkeypatch, invocation, provider, *, mismatch=None, approved=True):
    baseline = asyncio.run(experiments_diagnostics.capture_request(invocation))
    monkeypatch.setattr(settings, "DEFAULT_TEXT_MODEL_HARD", "gpt-5-mini")
    monkeypatch.setattr(settings, "EXPERIMENTS_SCHEMA_PROJECTION_ENABLED", True)
    monkeypatch.setattr(experiments_diagnostics, "restore_database", AsyncMock(return_value=invocation))
    install_transport(monkeypatch, provider)
    hashes = {"instructions": hashlib.sha256(baseline.arguments["instruction"].encode()).hexdigest(),
              "input": hashlib.sha256(baseline.arguments["text"].encode()).hexdigest(),
              "schema": schema_measurement(baseline.arguments["response_schema"])["sha256"]}
    recipe = (Path(__file__).parents[1] / "docs/runbooks/verify-experiments-projection.md").read_text(encoding="utf-8").split("```python\n", 1)[1].split("```", 1)[0]
    namespace = {}
    previous = logging.root.manager.disable
    try:
        exec(recipe.rsplit("\ntry:\n", 1)[0], namespace)
        namespace.update(APPROVED=approved, APPROVED_HASHES=hashes,
            APPROVED_PROVIDER_SCHEMA_HASH=schema_measurement(strip_schema_annotations(collapse_single_support_anyof(collapse_redundant_support_anyof(baseline.arguments["response_schema"])))[0])["sha256"])
        if mismatch == "provider":
            namespace["APPROVED_PROVIDER_SCHEMA_HASH"] = "0" * 64
        elif mismatch:
            hashes[mismatch] = "0" * 64
        summary = asyncio.run(namespace["verify"]())
        experiments_diagnostics.restore_database.assert_awaited_once_with(
            run_id=namespace["RUN_ID"], job_id=namespace["JOB_ID"])
        return summary
    finally:
        logging.disable(previous)


@pytest.mark.parametrize("rule,mutate,oi,ei", CASES)
def test_runbook_returns_safe_failure_rule(monkeypatch, invocation, rule, mutate, oi, ei):
    provider = provider_for(invocation, mutate)
    summary = run_recipe(monkeypatch, invocation, provider)
    assert summary["failure_rule"] == rule and not summary["accepted"]
    assert summary["http_calls"] == len(provider.calls) == 1
    assert summary.get("output_index") == oi and summary.get("experiment_index") == ei
    assert summary["http_status"] == 200 and summary["response_status"] == "completed"
    serialized = json.dumps(summary)
    assert all(secret not in serialized for secret in ("clm_", "evd_", "PRIVATE", "traceback"))
    assert summary["failure_rule"] in {rule.value for rule in ResultFailureRule}
    for field in ("output_index", "experiment_index"):
        if field in summary:
            assert type(summary[field]) is int and summary[field] >= 0
    from tests.experiments_provider import full_payload
    data = json.loads(provider.calls[0]["input"][1]["content"])
    # Only diagnostics/metadata may escape; fixture business content stays private.
    payload = full_payload(data)
    assert all(statement["text"] not in serialized for statement in payload["outputs"])
    assert all(parent_id not in serialized for parent_id in data["allowed_parent_claim_ids"])
    assert all(item["evidence_id"] not in serialized for item in data["local_evidence"])


@pytest.mark.parametrize("mismatch", ["instructions", "input", "schema", "provider"])
def test_runbook_fingerprint_mismatch_makes_zero_calls(monkeypatch, invocation, mismatch):
    provider = ExperimentsProvider()
    with pytest.raises(RuntimeError, match="^verification_(provider_)?fingerprint_mismatch$"):
        run_recipe(monkeypatch, invocation, provider, mismatch=mismatch)
    assert provider.calls == []


def test_runbook_approval_required(monkeypatch, invocation):
    provider = ExperimentsProvider()
    with pytest.raises(RuntimeError, match="^verification_not_approved_or_enabled$"):
        run_recipe(monkeypatch, invocation, provider, approved=False)
    assert provider.calls == []


@pytest.mark.parametrize("kind", ["OBSERVATION", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION"])
def test_schema_runtime_kind_mismatch_is_preserved(monkeypatch, invocation, kind):
    baseline = asyncio.run(experiments_diagnostics.capture_request(invocation))
    from tests.experiments_provider import full_payload
    payload = full_payload(json.loads(baseline.arguments["text"]))
    payload["outputs"][0]["kind"] = kind
    assert Draft202012Validator(baseline.arguments["response_schema"]).is_valid(payload)
    ExperimentsOutput.model_validate(payload)
    # Quote the parent so OBSERVATION passes the earlier intelligence check.
    def mutate(p):
        p["outputs"][0]["kind"] = kind
        if kind == "OBSERVATION":
            from app.module_execution.executors.claim_support import assertion_support
            parent = common.parent_claims(invocation)[p["outputs"][0]["parent_claim_ids"][0]]
            p["outputs"][0]["text"] = assertion_support(parent.value)[0]
    install_transport(monkeypatch, ExperimentsProvider(mutate))
    if kind in ("OBSERVATION", "INFERENCE"):
        with pytest.raises(ResultContractError) as caught:
            asyncio.run(ExperimentsExecutor(model_call=production_model_call).execute(invocation))
        assert caught.value.failure_rule is ResultFailureRule.OUTPUT_INVALID_KIND
        assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    else:
        asyncio.run(ExperimentsExecutor(model_call=production_model_call).execute(invocation))



@pytest.mark.parametrize("cause", ["normalization", "mutation", "other"])
def test_runbook_other_result_rules(monkeypatch, invocation, cause):
    if cause == "normalization":
        def reject(*args, **kwargs):
            raise ValueError("PRIVATE_MODEL_TEXT")
        monkeypatch.setattr(common, "NormalizedClaim", reject)
        expected = "result_normalization_invalid"
    elif cause == "mutation":
        original = ExperimentsExecutor.build_result
        def mutate(self, request, output, evidence, parents):
            output.outputs[1].text = "x" * 4001
            return original(self, request, output, evidence, parents)
        monkeypatch.setattr(ExperimentsExecutor, "build_result", mutate)
        expected = "post_mutation_pydantic_invalid"
    else:
        def reject(*args, **kwargs):
            raise TypeError("PRIVATE_MODEL_TEXT")
        monkeypatch.setattr(ExperimentsExecutor, "build_result", reject)
        expected = "other_result_contract_invalid"
    provider = ExperimentsProvider()
    summary = run_recipe(monkeypatch, invocation, provider)
    assert summary["failure_rule"] == expected and summary["failure"] == "result_contract_invalid"
    assert summary["http_calls"] == len(provider.calls) == 1 and not summary["accepted"]
    assert "PRIVATE" not in json.dumps(summary)


def test_first_actual_check_wins(monkeypatch, invocation):
    def mutate(payload):
        payload["outputs"][2]["parent_claim_ids"] = ["clm_z_additional_recommendation"]
        payload["experiments"][0]["related_strategic_claim_ids"] = ["clm_unknown", "clm_unknown"]
    provider = provider_for(invocation, mutate)
    install_transport(monkeypatch, provider)
    with pytest.raises(ResultContractError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=production_model_call).execute(invocation))
    assert caught.value.failure_rule is ResultFailureRule.OUTPUT_MISSING_STRATEGIC_PARENT
    # Without the earlier defect, the duplicate branch still precedes invalid refs.
    provider.mutate = lambda p: p["experiments"][0].update(related_strategic_claim_ids=["clm_unknown", "clm_unknown"])
    with pytest.raises(ResultContractError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=production_model_call).execute(invocation))
    assert caught.value.failure_rule is ResultFailureRule.EXPERIMENT_DUPLICATE_STRATEGIC_REFERENCES


def test_runbook_second_http_call_blocked(monkeypatch, invocation):
    from app.orchestration_runtime import model_adapter
    original = model_adapter.production_model_call
    async def twice(**kwargs):
        await original(**kwargs)
        return await original(**kwargs)
    monkeypatch.setattr(model_adapter, "production_model_call", twice)
    provider = ExperimentsProvider()
    with pytest.raises(RuntimeError, match="^verification_wire_or_call_limit$"):
        run_recipe(monkeypatch, invocation, provider)
    assert len(provider.calls) == 1



def test_runbook_defaults_match_latest_production_incident():
    # Inspect literal defaults without executing the recipe or contacting a DB/API.
    document = (Path(__file__).parents[1] / "docs/runbooks/verify-experiments-projection.md").read_text(encoding="utf-8")
    recipe = document.split("```python\n", 1)[1].split("```", 1)[0]
    expected = {
        "APPROVED": False,
        "RUN_ID": "4cc38ca6ed8c64b0039982fc8a83ff93bd3e165f89390052daa6cc3a718d785e",
        "JOB_ID": "c264b79d868e90f97a00c37d05ac43e6",
        "APPROVED_HASHES": {
            "instructions": "b9a6ae79b33e9d781251adbca9c659b279f8ed1965e8076a6b01bce0e02143eb",
            "input": "1bf797958c85b225429735385dae90e26f102c2c17071ea6e96d8cc425947c85",
            "schema": "49c9d21c942a1c5dd97af086fc1189e8d2f78ebd294edc58a1546b0e55560150",
        },
        "APPROVED_PROVIDER_SCHEMA_HASH": "27e6f30e45dd5aa10a5d5ee83a1e4529ec483e863f8d8c497c8cb80022582d68",
    }
    assignments = {}
    for node in ast.parse(recipe).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in expected:
                    assert target.id not in assignments  # No later conflicting default.
                    assignments[target.id] = ast.literal_eval(node.value)
    assert assignments == expected
    assert assignments["APPROVED"] is False
    assert f'Incident run: `{expected["RUN_ID"]}`.' in document
    assert f'Incident job: `{expected["JOB_ID"]}`.' in document
    assert "<approved_sha256>" not in document
