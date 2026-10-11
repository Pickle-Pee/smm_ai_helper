"""A fully accepted contextual quote cannot acquire experiment assertion authority."""
import json

import pytest

from app.module_execution.acceptance import fully_accepted
from app.module_execution.executors.claim_support import assertion_support, strategy_claim
from app.module_execution.executors.common import ExecutorOutputError
from app.module_execution.executors.intelligence_common import require_supported_numbers
from app.marketing_orchestrator.quality_gates import QualityGateEvaluator
from app.marketing_orchestrator.quality_gates.contracts import EvaluationBatch
from app.module_registry import ModuleId
from app.orchestration_runtime.serialization import result_from_json, result_to_json
from tests.test_module_executors import request
from tests.test_strategy_intelligence import IntelligenceModel, run, upstream
from tests.test_virtual_cmo_numeric_grounding import daycare_request, grounded_output, PRICE


def accepted_cmo(change=grounded_output):
    req = daycare_request()
    result = run(req, change)
    manifest = QualityGateEvaluator().evaluate(EvaluationBatch(batch_id="bat_context_boundary",
        results=tuple(u.result.normalized_result for u in req.upstream_results) +
                (result.normalized_result,))).synthesis_manifest
    assert fully_accepted(result, manifest.accepted_result_ids, manifest.accepted_claim_ids)
    return result_from_json(result_to_json(result))


@pytest.mark.parametrize("field", ["canonical", "hypothesis", "target_metric", "intervention",
    "expected_signal", "failure_condition", "minimum_required_inputs", "time_resource_constraints"])
@pytest.mark.parametrize("text", ["18 000 рублей", PRICE])
def test_accepted_context_cannot_support_experiment_numbers(field, text):
    parent = accepted_cmo()
    # Reproduce the exact old rule, even after real gates and durable roundtrip:
    require_supported_numbers(text, [str(parent.normalized_result.claims[0].value)])
    model = IntelligenceModel(use_parents=True)
    def laundering(raw, data):
        if field == "canonical":
            raw["outputs"][0]["text"] = text
        else:
            raw["experiments"][0][field] = [text] if field in (
                "minimum_required_inputs", "time_resource_constraints") else text
    with pytest.raises(ExecutorOutputError):
        run(request(ModuleId.EXPERIMENTS, facts=(), upstream=upstream(parent)), laundering, model=model)
    assert len(model.calls) == 1


def test_qualitative_continuation_preserves_identity_confidence_and_lineage():
    parent = accepted_cmo()
    result = run(request(ModuleId.EXPERIMENTS, facts=(), upstream=upstream(parent)))
    claim = result.normalized_result.claims[0]
    assert set(claim.parent_claim_ids) <= {c.claim_id for c in parent.normalized_result.claims}
    assert claim.parent_claim_ids
    assert claim.confidence.value == "MEDIUM"
    assert claim.lineage_type.value == "DERIVES"
    assert PRICE not in assertion_support(parent.normalized_result.claims[0].value)


@pytest.mark.parametrize("value", [
    '{"summary":"Safe","summary":"18 000 рублей","items":["Safe"]}',
    '{"summary":"Safe","items":["Safe"],"extra":"18 000 рублей"}',
    '{"summary":"Safe","items":[7]}',
    '{"summary":"Safe","items":["Safe"],"numeric_context":[{"quote":"18 000 рублей"}]}',
    '["18 000 рублей"]', '{broken',
])
def test_serialized_support_is_strict_and_fails_closed(value):
    assert strategy_claim(value) is None
    assert assertion_support(value) == ()


def test_plain_authorized_parent_numeric_support_is_unchanged():
    text = "Test a 20% conversion uplift hypothesis"
    assert assertion_support(text) == (text,)
    require_supported_numbers(text, assertion_support(text))


def test_legacy_envelopes_are_readable_without_numeric_authority_or_quote_normalization():
    old = json.dumps({"summary": "A 20% uplift hypothesis", "items": ["Compare messages"],
        "numeric_context": [{"support_id": "evd_source", "quote": " 18 000 рублей "}]})
    stored = strategy_claim(old)
    assert stored.numeric_context[0].attribution == "unknown"
    assert stored.numeric_context[0].quote == " 18 000 рублей "
    assert assertion_support(old) == ("Compare messages",)
    assert strategy_claim('{"summary":"Compare messages","items":["Test demand"]}') is not None


@pytest.mark.parametrize("source_key", ["site_claim", "owned_site_pricing"])
def test_site_quote_attribution_is_server_owned_and_survives_parent_continuation(source_key):
    quote = "Группы до 12 детей."
    from tests.test_module_executors import fact
    from app.marketing_copilot.presentation import module_presentation
    req = daycare_request()
    from dataclasses import replace
    req = replace(req, context_packet=replace(req.context_packet,
        known_facts=tuple(f for f in req.context_packet.known_facts if f.label != "site_claim") +
        (fact(source_key, quote if source_key == "site_claim" else
              {"trust": "site_claim", "site_states": [quote]}),)))
    def site(raw, data):
        grounded_output(raw, data)
        source = next(e for e in data["local_evidence"] if e["input_key"] == source_key)
        raw["outputs"][0]["evidence_ids"].append(source["evidence_id"])
        raw["outputs"][0]["numeric_context"] = [{"support_id": source["evidence_id"], "quote": quote}]
    parent = run(req, site)
    def inherit(raw, data):
        raw["outputs"][0]["numeric_context"] = [{"support_id": parent.normalized_result.claims[0].claim_id, "quote": quote}]
    child = run(replace(req, execution_id="virtual_cmo.exec:2", upstream_results=upstream(parent)), inherit)
    for result in (parent, result_from_json(result_to_json(parent)), child):
        displayed = module_presentation(result).strategic_diagnosis.numeric_context[0]
        assert "На сайте заявлено (не подтверждено владельцем)" in displayed
        assert quote in displayed
        assert "evd_" not in displayed and "clm_" not in displayed


@pytest.mark.parametrize("quote", ["snapshot_123456", "evd_123456", "clm_123456"])
def test_owned_site_metadata_is_not_a_quote_channel(quote):
    from dataclasses import replace
    from tests.test_module_executors import fact
    from app.module_execution.executors.numeric_grounding import context_units
    source = {"trust": "site_claim", "site_states": ["Группы до 12 детей."],
              "snapshot_id": "snapshot_123456", "evidence": [{
                  "record": {"evidence_id": "evd_123456"}, "claim_id": "clm_123456"}]}
    # The former unrestricted walker would authorize all these technical leaves.
    assert tuple(context_units(source)) == ("Группы до 12 детей.",)
    req = daycare_request()
    req = replace(req, context_packet=replace(req.context_packet,
        known_facts=(*req.context_packet.known_facts, fact("owned_site_pricing", source))))
    def metadata(raw, data):
        source_id = next(e["evidence_id"] for e in data["local_evidence"]
                         if e["input_key"] == "owned_site_pricing")
        raw["outputs"][0]["evidence_ids"].append(source_id)
        raw["outputs"][0]["numeric_context"] = [{"support_id": source_id, "quote": quote}]
    model = IntelligenceModel(use_parents=True)
    with pytest.raises(ExecutorOutputError):
        run(req, metadata, model=model)
    assert len(model.calls) == 1
