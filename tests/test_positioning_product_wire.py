"""Offline product-support contract matrix and explicit lineage mapping."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from app.module_execution import UpstreamExecutionResult, ModuleExecutionContractError
from app.module_execution.executors import PositioningExecutor, ExecutorOutputError
from app.module_execution.executors.common import first_party_evidence, scoped_facts, plain
from app.module_execution.executors.product_support import (
    PRODUCT_OUTPUTS, WIRE_VERSION, product_wire_schema, decode_product_wire,
)
from app.module_execution.executors.provider_schema import schema_measurement, nodes
from app.module_execution.executors.support_schema import support_response_schema
from app.module_registry import ModuleId
from app.orchestration_runtime.serialization import result_to_json, result_from_json
from app.orchestration_runtime.worker import transient
from tests.test_module_executors import FakeModel, dispatch, fact, request
from tests.test_positioning_seed_contract import seed_request, STATES, KINDS


MODES = ("truth", "proof", "mixed", "wrong_category", "parent_only", "missing", "invented")


class ProductModel(FakeModel):
    """Synthetic model explicitly selects the scalar; no application repair."""
    def __init__(self, mode="truth", kind="HYPOTHESIS", mutate=None):
        super().__init__()
        self.mode, self.kind, self.change = mode, kind, mutate
        self.payload = None

    async def __call__(self, **kwargs):
        payload = json.loads(await super().__call__(**kwargs))
        data = json.loads(kwargs["text"])
        ids = {e["input_key"]: e["evidence_id"] for e in data["local_evidence"]}
        payload["wire_contract_version"] = WIRE_VERSION
        for statement in payload["outputs"]:
            if statement["output_name"] not in PRODUCT_OUTPUTS:
                continue
            statement.update(kind=self.kind, evidence_ids=[], parent_claim_ids=[])
            if self.mode in {"truth", "mixed"}:
                statement["product_support_id"] = ids["product_truth"]
            elif self.mode == "proof":
                statement["product_support_id"] = ids["existing_proof"]
            elif self.mode == "wrong_category":
                statement["product_support_id"] = ids["product"]
            elif self.mode == "invented":
                statement["product_support_id"] = "evd_invented"
            if self.mode in {"mixed", "parent_only"}:
                statement["parent_claim_ids"] = data["allowed_parent_claim_ids"][:1]
            if self.mode == "mixed":
                statement["evidence_ids"] = [ids["product"], ids["existing_proof"]]
        if self.kind == "OBSERVATION":
            # Simulate a canonical/legacy caller despite the provider subset:
            # positive OBS cases must cite their exact actual product source.
            for statement in payload["outputs"]:
                selected = statement.get("product_support_id")
                source = next((e for e in data["local_evidence"] if e["evidence_id"] == selected), None)
                if source is not None:
                    statement["text"] = source["value"]
        if self.change:
            self.change(payload, data)
        self.payload = deepcopy(payload)
        return json.dumps(payload)


def invocation(job, alternative, outputs=None):
    parent = dispatch(request(ModuleId.POSITIONING, outputs=("target",)))
    req = seed_request(job, alternative, outputs=outputs, upstream=(
        UpstreamExecutionResult(producer_node_id="parent", result=parent),))
    return replace(req, execution_id="c" * 32, context_packet=replace(req.context_packet,
        known_facts=(*req.context_packet.known_facts, fact("existing_proof"))))


def execute(req, model, projection=False):
    return asyncio.run(PositioningExecutor(model_call=model, product_support_wire=True,
        provider_schema_projection=projection).execute(req))


@pytest.mark.parametrize("name", sorted(PRODUCT_OUTPUTS))
@pytest.mark.parametrize("kind", sorted(KINDS))
@pytest.mark.parametrize("job,alternative", STATES)
@pytest.mark.parametrize("mode", MODES)
def test_product_matrix(name, kind, job, alternative, mode):
    req = invocation(job, alternative, outputs=(name,))
    model = ProductModel(mode, kind)
    valid = mode in {"truth", "proof", "mixed"}
    if valid:
        result = execute(req, model)
        selected = model.payload["outputs"][0]["product_support_id"]
        claim = result.normalized_result.claims[0]
        assert selected in claim.evidence_ids
        assert claim.claim_type.value == kind
        assert set(result.payload["outputs"][0]["evidence_ids"]) == set(claim.evidence_ids)
        assert set(claim.evidence_ids) == {selected, *model.payload["outputs"][0]["evidence_ids"]}
        assert claim.parent_claim_ids == tuple(model.payload["outputs"][0]["parent_claim_ids"])
        assert "product_support_id" not in result.payload["outputs"][0]
        assert "wire_contract_version" not in result.payload
        assert result.schema_version == "positioning.payload.v1"
        assert result_from_json(result_to_json(result)) == result
    else:
        with pytest.raises(ExecutorOutputError) as caught:
            execute(req, model)
        assert caught.value.stage.value == "schema_invalid"
        assert not transient(caught.value)
    assert len(model.calls) == 1
    assert Draft202012Validator(model.calls[0]["response_schema"]).is_valid(model.payload) is (valid and kind != "OBSERVATION")


@pytest.mark.parametrize("job,alternative", STATES)
@pytest.mark.parametrize("projection", [False, True])
def test_all_outputs_compatibility_and_provider_subset(job, alternative, projection):
    req = invocation(job, alternative)
    old = dispatch(req)
    model = ProductModel()
    new = execute(req, model, projection)
    assert old.schema_version == new.schema_version
    assert len(old.normalized_result.claims) == len(new.normalized_result.claims) == 16
    old_statements = {s["output_name"]: s for s in old.payload["outputs"]}
    for statement, claim in zip(new.payload["outputs"], new.normalized_result.claims):
        previous = old_statements[statement["output_name"]]
        if statement["output_name"] not in PRODUCT_OUTPUTS:
            assert statement == previous
        else:
            assert claim.evidence_ids == (model.payload["outputs"][list(old_statements).index(
                statement["output_name"])]["product_support_id"],)
    schema = model.calls[0]["response_schema"]
    assert "anyOf" not in schema
    for node in nodes(schema):
        assert set(node) <= {"type", "properties", "required", "additionalProperties", "$defs",
                             "$ref", "anyOf", "enum", "const", "items", "minLength", "maxLength",
                             "minItems", "maxItems", "title", "description"}
        assert not {"contains", "minContains", "allOf", "not", "oneOf", "if", "then", "else",
                    "uniqueItems", "dependentRequired", "dependentSchemas"}.intersection(node)
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
    evidence = first_party_evidence(req, scoped_facts(req))
    assert schema["$defs"]["AllowedProductSupportId"]["enum"] == sorted(
        e.record.evidence_id for e in evidence if e.input_key in {"product_truth", "existing_proof"})


@pytest.mark.parametrize("mutation", [
    lambda p,d: p.pop("wire_contract_version"),
    lambda p,d: p.update(wire_contract_version="positioning.wire.v1"),
    lambda p,d: p["outputs"][0].update(product_support_id=None),
    lambda p,d: p["outputs"][0].update(evidence_ids=[p["outputs"][0]["product_support_id"]]),
    lambda p,d: p["outputs"][0].update(evidence_ids=["evd_invented"]),
    lambda p,d: p["outputs"][0].update(parent_claim_ids=["clm_invented"]),
])
def test_no_fallback_no_duplicate_repair(mutation):
    model = ProductModel(mutate=mutation)
    with pytest.raises(ExecutorOutputError):
        execute(invocation(True, True, outputs=("RTB",)), model)
    assert len(model.calls) == 1


@pytest.mark.parametrize("job,alternative", STATES)
def test_schema_bounds_at_maximum_support(job, alternative):
    req = invocation(job, alternative)
    original = first_party_evidence(req, scoped_facts(req))
    # Wire-builder bound (128), deliberately beyond the narrower persisted ID
    # grammar: schema budgeting must still reject no permitted boundary values.
    evidence = tuple(SimpleNamespace(input_key="product_truth",
        record=SimpleNamespace(evidence_id=f"evd_{i:0124}")) for i in range(250))
    executor = PositioningExecutor(model_call=None)
    schema = support_response_schema(executor.output_type_for(req, original),
        [e.record.evidence_id for e in evidence], [f"clm_{i:0124}" for i in range(250)])
    wire = product_wire_schema(schema, evidence)
    assert len(wire["$defs"]["AllowedProductSupportId"]["enum"]) == 250
    assert schema_measurement(wire)["bytes"] < 130000
    with pytest.raises(ModuleExecutionContractError):
        product_wire_schema(schema, ())


def test_original_v1_result_roundtrip_and_v2_cannot_accept_v1_response():
    req = invocation(True, True, outputs=("RTB",))
    old = dispatch(req)
    assert result_from_json(result_to_json(old)) == old
    with pytest.raises(ExecutorOutputError):
        execute(req, FakeModel())


def test_explicit_mapping_preserves_accepted_v1_lineage():
    req = invocation(True, True)
    old = dispatch(req)
    encoded = plain(old.payload)
    encoded["wire_contract_version"] = WIRE_VERSION
    evidence = first_party_evidence(req, scoped_facts(req))
    truth = next(e.record.evidence_id for e in evidence if e.input_key == "product_truth")
    for statement in encoded["outputs"]:
        if statement["output_name"] in PRODUCT_OUTPUTS:
            statement["product_support_id"] = truth
            statement["evidence_ids"].remove(truth)
    decoded = decode_product_wire(encoded, evidence)
    for previous, current in zip(plain(old.payload)["outputs"], decoded["outputs"]):
        assert set(previous["evidence_ids"]) == set(current["evidence_ids"])
        assert previous["parent_claim_ids"] == current["parent_claim_ids"]


@pytest.mark.parametrize("job,alternative", STATES)
@pytest.mark.parametrize("projection", [False, True])
def test_real_adapter_mock_transport_and_quality_gates(monkeypatch, job, alternative, projection):
    import httpx
    from app.orchestration_runtime.model_adapter import production_model_call
    from app.orchestration_runtime.service import evaluate_result
    from app.module_execution.acceptance import fully_accepted
    from tests.test_graph_model_adapter import install_transport
    req = invocation(job, alternative)
    synthetic = ProductModel()
    execute(req, synthetic, projection)
    seen = []
    def respond(http_request):
        body = json.loads(http_request.content)
        seen.append(body)
        assert body["text"]["format"]["strict"] is True
        assert body["text"]["format"]["schema"] == synthetic.calls[0]["response_schema"]
        return httpx.Response(200, json={"status": "completed", "output_text": json.dumps(synthetic.payload)})
    install_transport(monkeypatch, respond)
    result = execute(req, production_model_call, projection)
    quality = evaluate_result(req.execution_id, result, req.upstream_results)
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])
    assert len(seen) == 1


@pytest.mark.parametrize("mode,stage", [("blank", "schema_invalid"), ("duplicate", "support_identity_invalid"),
                                      ("coverage", "output_coverage_invalid")])
def test_original_validation_layers_remain_authoritative(mode, stage):
    def mutate(p,d):
        statement = p["outputs"][0]
        if mode == "blank":
            statement["text"] = "   "  # JSON Schema valid; original Pydantic rejects.
        elif mode == "duplicate":
            extra = next(e["evidence_id"] for e in d["local_evidence"] if e["input_key"] == "product")
            statement["evidence_ids"] = [extra, extra]
        else:
            p["outputs"].append(deepcopy(statement))
    model = ProductModel(mutate=mutate)
    with pytest.raises(ExecutorOutputError) as caught:
        execute(invocation(True, True, outputs=("RTB",)), model)
    assert caught.value.stage.value == stage
    assert len(model.calls) == 1
    assert Draft202012Validator(model.calls[0]["response_schema"]).is_valid(model.payload)


def test_wire_fingerprints_distinguish_original_wire_and_projection(monkeypatch, caplog):
    import logging
    from app.module_execution.executors.common import log
    monkeypatch.setattr(log, "disabled", False)
    caplog.set_level(logging.INFO, logger=log.name)
    req = invocation(False, False, outputs=("RTB",))
    model = ProductModel()
    execute(req, model, True)
    contract = next(r for r in caplog.records if r.msg.startswith("Module wire schemas"))
    provider = next(r for r in caplog.records if r.msg.startswith("POSITIONING provider schema")
                    and hasattr(r, "wire_contract_version"))
    assert provider.wire_schema_sha256 == contract.wire_schema_sha256
    assert provider.provider_schema_sha256 == contract.provider_schema_sha256
    assert contract.validation_schema_sha256 != contract.wire_schema_sha256
    assert contract.provider_schema_sha256 == schema_measurement(model.calls[0]["response_schema"])["sha256"]


def test_semantic_defense_and_rejection_fingerprint_correlation(monkeypatch, caplog):
    import logging
    from app.module_execution.executors.common import log
    monkeypatch.setattr(log, "disabled", False)
    caplog.set_level(logging.INFO, logger=log.name)
    original_decode = PositioningExecutor.decode_wire_payload
    def corrupt_mapping(self, req, payload, evidence):
        result = original_decode(self, req, payload, evidence)
        result["outputs"][0]["evidence_ids"] = [
            next(e.record.evidence_id for e in evidence if e.input_key == "product")]
        return result
    monkeypatch.setattr(PositioningExecutor, "decode_wire_payload", corrupt_mapping)
    model = ProductModel(mutate=lambda p,d: p["outputs"][0].update(text="PRIVATE_CLAIM"))
    with pytest.raises(ExecutorOutputError) as caught:
        execute(invocation(False, False, outputs=("RTB",)), model, True)
    assert caught.value.stage.value == "statement_semantics_invalid"
    contract = next(r for r in caplog.records if r.msg.startswith("Module wire schemas"))
    # B also runs independently of diagnostic-only A. When composed with A,
    # additionally prove the rejection event uses the same authoritative hashes.
    for rejection in (r for r in caplog.records if r.msg.startswith("Module statement diagnostic")):
        assert rejection.validation_schema_sha256 == contract.validation_schema_sha256
        assert rejection.provider_schema_sha256 == contract.provider_schema_sha256
        assert rejection.evidence_categories == ["product"]
    assert "PRIVATE_CLAIM" not in caplog.text
    assert "evd_" not in caplog.text
    assert len(model.calls) == 1
