"""Equivalent provider wire, original validation, independent switches and gates."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
import logging
from unittest.mock import AsyncMock

import pytest
from jsonschema import Draft202012Validator

from app.config import Settings, settings
from app.module_execution.acceptance import fully_accepted
from app.module_execution.executors import ExperimentsExecutor, ExecutorOutputError
from app.module_execution.executors import common, experiments as experiment_module
from app.module_execution.executors.provider_schema import SchemaProjectionError, schema_measurement, collapse_redundant_support_anyof, collapse_single_support_anyof
from app.module_execution.executors.schema_annotations import strip_schema_annotations
from app.module_execution.executors.intelligence_schemas import ExperimentsOutput
from app.module_registry import ModuleId
from app.orchestration_runtime.composition import build_production_graph_runtime
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.service import evaluate_result
from app.orchestration_runtime.worker import transient
from tests.experiments_provider import ExperimentsProvider, full_payload
from tests.test_experiments_diagnostics import restored, snapshot, RUN_ID
from tests.test_graph_model_adapter import install_transport
from tests.test_module_executors import analyzer
from tests.test_production_graph_worker import queue
from tests.test_strategy_intelligence import valid_request
from tools.experiments_diagnostics import capture_request, restore_snapshot, schema_matrix


@pytest.mark.parametrize("enabled", [False, True])
def test_real_wire_original_validation_all_outputs_designs_and_gates(monkeypatch, caplog, enabled):
    invocation = restored()
    monkeypatch.setattr(settings, "DEFAULT_TEXT_MODEL_HARD", "gpt-5-mini")
    baseline = asyncio.run(capture_request(invocation))
    original = deepcopy(baseline.arguments["response_schema"])
    projected, removed = strip_schema_annotations(collapse_single_support_anyof(collapse_redundant_support_anyof(original)))
    validators = []
    factory = common.Draft202012Validator
    def track(schema):
        validators.append(deepcopy(schema))
        return factory(schema)
    monkeypatch.setattr(common, "Draft202012Validator", track)
    pydantic_calls = []
    validate = ExperimentsOutput.model_validate_json
    def track_pydantic(raw, **kwargs):
        pydantic_calls.append(True)
        return validate(raw, **kwargs)
    monkeypatch.setattr(ExperimentsOutput, "model_validate_json", track_pydantic)
    monkeypatch.setattr(common.log, "disabled", False)
    provider = ExperimentsProvider()
    install_transport(monkeypatch, provider)
    with caplog.at_level(logging.INFO, logger=common.log.name):
        result = asyncio.run(ExperimentsExecutor(model_call=production_model_call,
            provider_schema_projection=enabled).execute(invocation))
    assert validators == [original]
    assert pydantic_calls == [True]
    expected = deepcopy(baseline.payload)
    expected["text"]["format"]["schema"] = projected if enabled else original
    assert provider.calls == [expected]  # Includes model, Expert Core, input and all budget/policy fields.
    assert expected["model"] == "gpt-5-mini" and expected["max_output_tokens"] == 16000
    assert len(result.payload["outputs"]) == 16 and len(result.payload["experiments"]) == 3
    assert {c.declared_output_name for c in result.normalized_result.claims} == set(invocation.expected_outputs)
    quality = evaluate_result(invocation.execution_id, result, invocation.upstream_results)
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])
    excluded = result.normalized_result.claims[0].claim_id
    assert not fully_accepted(result, quality["accepted_result_ids"], [c for c in quality["accepted_claim_ids"] if c != excluded])
    record = next(r for r in caplog.records if r.getMessage().startswith("EXPERIMENTS provider schema "))
    assert record.schema_projection_enabled is enabled
    assert record.schema_projection_applied is enabled
    assert record.schema_projection_annotations_removed == (removed if enabled else 0)
    assert record.validation_schema_sha256 == schema_measurement(original)["sha256"]
    assert record.validation_schema_bytes == schema_measurement(original)["bytes"]
    wire_schema = expected["text"]["format"]["schema"]
    assert record.provider_schema_sha256 == schema_measurement(wire_schema)["sha256"]
    assert record.provider_schema_bytes == schema_measurement(wire_schema)["bytes"]
    assert all(token not in record.getMessage() for token in ("evd_", "clm_", "Supplied", invocation.execution_id))


def test_literals_extensions_property_names_and_boolean_nodes_are_opaque():
    literal = {"title": "literal", "description": "literal", "examples": [{"default": 1}]}
    schema = {"type": "object", "title": "annotation", "default": literal,
        "properties": {"title": {"const": literal, "description": "annotation"},
                       "description": {"enum": [literal], "examples": [literal]}},
        "$defs": {"default": {"type": "string", "title": "annotation"}},
        "allOf": [True, {"title": "annotation"}], "x-user-data": literal,
        "additionalProperties": False}
    before = deepcopy(schema)
    projected, count = strip_schema_annotations(schema)
    assert schema == before and projected is not schema and count == 6
    assert projected["properties"]["title"]["const"] == literal
    assert projected["properties"]["description"]["enum"] == [literal]
    assert projected["x-user-data"] == literal and "default" in projected["$defs"]
    projected["properties"]["title"]["const"]["title"] = "changed"
    assert schema == before


@pytest.mark.parametrize("mutation,valid", [
    (lambda p: None, True),
    (lambda p: p["outputs"][0].update(parent_claim_ids=[]), False),
    (lambda p: p["outputs"][0].update(parent_claim_ids=["clm_unknown"]), False),
    (lambda p: p["outputs"][0].update(text=""), False),
    (lambda p: p["outputs"][0].update(text="x" * 4001), False),
    (lambda p: p.update(outputs=[]), False),
    (lambda p: p.update(experiments=[]), False),
    (lambda p: p["experiments"].append(deepcopy(p["experiments"][0])), False),
    (lambda p: p["experiments"][0].update(minimum_required_inputs=[]), False),
    (lambda p: p["experiments"][0].update(related_strategic_claim_ids=[]), False),
    (lambda p: p["experiments"][0].update(hypothesis="x" * 1001), False),
])
def test_formal_schema_equivalence(mutation, valid):
    baseline = asyncio.run(capture_request(restored()))
    original = baseline.arguments["response_schema"]
    projected, _ = strip_schema_annotations(collapse_single_support_anyof(collapse_redundant_support_anyof(original)))
    # Every assertion and schema edge is identical; only annotation nodes differ.
    assert "anyOf" not in projected["$defs"]["ExperimentStatement"]
    payload = full_payload(json.loads(baseline.arguments["text"]))
    mutation(payload)
    assert Draft202012Validator(original).is_valid(payload) is valid
    assert Draft202012Validator(projected).is_valid(payload) is valid


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("mutation", [
    lambda p: p["outputs"][0].update(parent_claim_ids=["clm_unknown"]),
    lambda p: p["outputs"][0].update(parent_claim_ids=[]),
    lambda p: p["outputs"][0].update(evidence_ids=["evd_unknown"]),
    lambda p: p["outputs"][0].update(kind="OBSERVATION"),
    lambda p: p["outputs"][0].update(text="Guaranteed 90% uplift"),
    lambda p: p["outputs"].pop(),
    lambda p: p["experiments"][0].update(related_strategic_claim_ids=["clm_unknown"]),
    lambda p: p["experiments"][0]["related_strategic_claim_ids"].append(p["experiments"][0]["related_strategic_claim_ids"][0]),
    lambda p: p["experiments"][0].update(expected_signal="Expected uplift 20%"),
    lambda p: p["experiments"][0].update(time_resource_constraints=["Budget 500 dollars"]),
    lambda p: p["experiments"][0].update(minimum_required_inputs=[]),
])
def test_server_pipeline_rejects_invalid_outputs_once(monkeypatch, enabled, mutation):
    provider = ExperimentsProvider(mutation)
    install_transport(monkeypatch, provider)
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=production_model_call,
            provider_schema_projection=enabled).execute(restored()))
    assert not transient(caught.value) and len(provider.calls) == 1


@pytest.mark.parametrize("positioning", [False, True])
@pytest.mark.parametrize("experiments", [False, True])
def test_independent_production_switches_and_unprojected_diagnostics(monkeypatch, positioning, experiments):
    monkeypatch.setattr(settings, "POSITIONING_SCHEMA_PROJECTION_ENABLED", positioning)
    monkeypatch.setattr(settings, "EXPERIMENTS_SCHEMA_PROJECTION_ENABLED", experiments)
    runtime = build_production_graph_runtime(queue=queue(), analyzer=analyzer())
    assert runtime.executors.resolve("positioning.v1")._provider_schema_projection is positioning
    assert runtime.executors.resolve("experiments.v1")._provider_schema_projection is experiments
    for key in ("creator.v1", "market_analysis.v1", "competitor_analysis.v1"):
        assert type(runtime.executors.resolve(key)).provider_schema_for is common.BaseExecutor.provider_schema_for
    from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
    assert type(runtime.executors.resolve("virtual_cmo.v1")) is VirtualCMOExecutor
    invocation = restored()
    baseline = asyncio.run(capture_request(invocation))
    provider = ExperimentsProvider()
    install_transport(monkeypatch, provider)
    asyncio.run(runtime.executors.resolve("experiments.v1").execute(invocation))
    original = baseline.arguments["response_schema"]
    assert provider.calls[0]["text"]["format"]["schema"] == (strip_schema_annotations(collapse_single_support_anyof(collapse_redundant_support_anyof(original)))[0] if experiments else original)
    assert asyncio.run(capture_request(invocation)).arguments == baseline.arguments
    assert Settings.model_fields["EXPERIMENTS_SCHEMA_PROJECTION_ENABLED"].default is False


@pytest.mark.parametrize("schema", [
    {"type": "invalid"}, {"$ref": "#/default", "default": {"type": "string"}},
    {"$ref": "https://remote.test/schema"}, {"$schema": "custom"}, {"$vocabulary": {}},
    {"$id": "urn:scope"}, {"$dynamicRef": "#foo"}, {"default": float("nan")},
])
def test_fail_closed_safe_error_and_no_mutation(schema):
    before = json.dumps(schema)
    with pytest.raises(SchemaProjectionError, match="^annotation_projection_not_equivalent$"):
        strip_schema_annotations(schema)
    assert json.dumps(schema) == before


def test_projection_failure_prevents_provider_call(monkeypatch):
    model = AsyncMock()
    def refuse(schema):
        raise SchemaProjectionError("safe_refusal")
    monkeypatch.setattr(experiment_module, "strip_schema_annotations", refuse)
    with pytest.raises(SchemaProjectionError) as caught:
        asyncio.run(ExperimentsExecutor(model_call=model, provider_schema_projection=True).execute(restored()))
    assert not transient(caught.value)
    model.assert_not_called()


def test_provider_mutation_cannot_weaken_original_validator():
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        kwargs["response_schema"].clear()
        payload = full_payload(data)
        payload["outputs"][0]["text"] = ""
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError):
        asyncio.run(ExperimentsExecutor(model_call=model, provider_schema_projection=True).execute(restored()))


@pytest.mark.parametrize("enabled", [False, True])
def test_no_strategic_parent_blocks_before_provider(enabled):
    invocation = replace(valid_request(ModuleId.EXPERIMENTS), upstream_results=())
    model = AsyncMock()
    result = asyncio.run(ExperimentsExecutor(model_call=model, provider_schema_projection=enabled).execute(invocation))
    assert result.normalized_result.module_status.value == "BLOCKED"
    model.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_constraints_preserved_verbatim_and_missing_constraint_rejected(enabled):
    source, jid = snapshot(constraints=("Budget 500 dollars", "Duration 14 days"))
    invocation = asyncio.run(restore_snapshot(source, run_id=RUN_ID, job_id=jid))
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        payload = full_payload(data)
        for design in payload["experiments"]:
            design["time_resource_constraints"] = data["context"]["constraints"]
        return json.dumps(payload)
    executor = ExperimentsExecutor(model_call=model, provider_schema_projection=enabled)
    result = asyncio.run(executor.execute(invocation))
    assert all(tuple(d["time_resource_constraints"]) == invocation.context_packet.constraints for d in result.payload["experiments"])
    quality = evaluate_result(jid, result, invocation.upstream_results)
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])
    async def omit(**kwargs):
        payload = json.loads(await model(**kwargs))
        payload["experiments"][0]["time_resource_constraints"].pop()
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError):
        asyncio.run(ExperimentsExecutor(model_call=omit, provider_schema_projection=enabled).execute(invocation))


@pytest.mark.parametrize("enabled", [False, True])
def test_supplied_numeric_hypothesis_is_allowed_verbatim(enabled):
    invocation = valid_request(ModuleId.EXPERIMENTS)
    upstream = invocation.upstream_results[0]
    normalized = upstream.result.normalized_result
    sentence = "Test a 20% conversion uplift hypothesis"
    from app.orchestration_runtime.serialization import result_to_json
    parent = replace(upstream.result, payload=result_to_json(upstream.result)["payload"],
        normalized_result=replace(normalized, claims=(replace(normalized.claims[0], value=sentence),)))
    invocation = replace(invocation, upstream_results=(replace(upstream, result=parent),))
    async def model(**kwargs):
        payload = full_payload(json.loads(kwargs["text"]))
        payload["outputs"][0]["text"] = sentence
        payload["experiments"][0]["expected_signal"] = sentence
        return json.dumps(payload)
    result = asyncio.run(ExperimentsExecutor(model_call=model, provider_schema_projection=enabled).execute(invocation))
    assert result.payload["outputs"][0]["text"] == sentence
    assert result.payload["experiments"][0]["expected_signal"] == sentence


def test_runbook_recipe_is_parseable_and_unapproved():
    import ast
    from pathlib import Path
    recipe = (Path(__file__).parents[1] / "docs/runbooks/verify-experiments-projection.md").read_text(encoding="utf-8").split("```python\n", 1)[1].split("```", 1)[0]
    tree = ast.parse(recipe)
    approved = next(n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "APPROVED")
    assert approved.value.value is False


@pytest.mark.parametrize("index", range(16))
def test_every_canonical_output_requires_strategic_citation(index):
    invocation = restored()
    async def model(**kwargs):
        payload = full_payload(json.loads(kwargs["text"]))
        payload["outputs"][index]["parent_claim_ids"] = []
        return json.dumps(payload)
    with pytest.raises(ExecutorOutputError):
        asyncio.run(ExperimentsExecutor(model_call=model, provider_schema_projection=True).execute(invocation))


def test_runbook_executes_full_acceptance_with_mock_transport(monkeypatch):
    from pathlib import Path
    from tools import experiments_diagnostics
    invocation = restored()
    monkeypatch.setattr(settings, "DEFAULT_TEXT_MODEL_HARD", "gpt-5-mini")
    monkeypatch.setattr(settings, "EXPERIMENTS_SCHEMA_PROJECTION_ENABLED", True)
    baseline = asyncio.run(capture_request(invocation))
    import hashlib
    hashes = {"instructions": hashlib.sha256(baseline.arguments["instruction"].encode("utf-8")).hexdigest(),
              "input": hashlib.sha256(baseline.arguments["text"].encode("utf-8")).hexdigest(),
              "schema": schema_measurement(baseline.arguments["response_schema"])["sha256"]}
    monkeypatch.setattr(experiments_diagnostics, "restore_database", AsyncMock(return_value=invocation))
    provider = ExperimentsProvider()
    install_transport(monkeypatch, provider)
    recipe = (Path(__file__).parents[1] / "docs/runbooks/verify-experiments-projection.md").read_text(encoding="utf-8").split("```python\n", 1)[1].split("```", 1)[0]
    # Load only the recipe definitions; the live entrypoint stays unexecuted.
    namespace = {}
    previous_logging = logging.root.manager.disable
    try:
        exec(recipe.rsplit("\ntry:\n", 1)[0], namespace)
        namespace.update(APPROVED=True, APPROVED_HASHES=hashes,
            APPROVED_PROVIDER_SCHEMA_HASH=schema_measurement(strip_schema_annotations(collapse_single_support_anyof(collapse_redundant_support_anyof(baseline.arguments["response_schema"])))[0])["sha256"])
        summary = asyncio.run(namespace["verify"]())
    finally:
        logging.disable(previous_logging)
    assert summary["accepted"] is True and summary["http_calls"] == 1
    assert summary["response_status"] == "completed" and summary["quality_gate_accepted"]
    assert summary["output_count"] == 16 and summary["experiment_design_count"] == 3
    assert len(provider.calls) == 1
