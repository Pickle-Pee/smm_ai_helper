"""Catalog acceptance policy through actual HTTP adapter, dispatcher and gates."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
import logging
from types import SimpleNamespace

import pytest

from app.marketing_orchestrator.quality_gates.contracts import AuthorityStatus, Confidence
from app.module_execution import ModuleExecutorDispatcher
from app.module_execution.executors import build_module_executor_registry
from app.module_execution.executors.common import (
    ExecutorOutputError, first_party_evidence, parent_claims, scoped_facts, plain,
)
from app.module_execution.executors.numeric_grounding import bind_numeric_context_citations
from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
from app.module_registry import ModuleId, ModuleRegistry
from app.orchestration_runtime.model_adapter import production_model_call
from tests.test_graph_model_adapter import install_transport
from tests.test_module_executors import analyzer, fact, request
from tests.test_strategy_intelligence import positioning, upstream
from tests.test_virtual_cmo_numeric_grounding import AGE, PRICE, daycare_facts, daycare_request, grounded_output
from tests.test_virtual_cmo_quote_catalog import NumericProvider, gate


def dispatch(req, enabled=True):
    registry = build_module_executor_registry(model_call=production_model_call, analyzer=analyzer(),
        registry_version="1.3.0", virtual_cmo_numeric_quote_catalog=enabled)
    return asyncio.run(ModuleExecutorDispatcher(registry).dispatch(
        ModuleRegistry.load("1.3.0").get(ModuleId.VIRTUAL_CMO).execution_binding, req))


def missing_local(raw, data):
    grounded_output(raw, data)
    raw["outputs"][0]["evidence_ids"] = []  # explicit strategic parent remains


def test_exact_missing_local_bindings_equal_explicit_citations_and_gates(monkeypatch, caplog):
    from app.module_execution.executors.virtual_cmo import log
    monkeypatch.setattr(log, "disabled", False)
    caplog.set_level(logging.INFO, logger=log.name)
    req = daycare_request()
    provider = NumericProvider(missing_local)
    install_transport(monkeypatch, provider)
    normalized = dispatch(req)
    record = next(r for r in caplog.records if "numeric_context_citation_bound" in r.getMessage())
    assert record.getMessage() == ("Module output normalized module=VIRTUAL_CMO "
        "code=numeric_context_citation_bound normalized_reference_count=2")
    assert AGE not in caplog.text and PRICE not in caplog.text
    assert len(provider.calls) == 1
    provider.mutate = grounded_output
    explicit = dispatch(req)
    assert len(provider.calls) == 2
    assert normalized == explicit
    assert gate(normalized, req) == gate(explicit, req)
    assert normalized.normalized_result.result_id in gate(normalized, req).synthesis_manifest.accepted_result_ids
    for identity in (*normalized.payload["outputs"][0]["evidence_ids"],
                     *normalized.payload["outputs"][0]["parent_claim_ids"]):
        assert identity not in record.getMessage()


def test_already_cited_and_repeated_context_add_no_duplicate_references(monkeypatch, caplog):
    def repeated(raw, data):
        missing_local(raw, data)
        raw["outputs"][0]["numeric_context"].append(raw["outputs"][0]["numeric_context"][0].copy())
    provider = NumericProvider(repeated)
    install_transport(monkeypatch, provider)
    result = dispatch(daycare_request())
    refs = result.payload["outputs"][0]["evidence_ids"]
    assert len(refs) == len(set(refs)) == 2
    assert len(result.payload["outputs"][0]["numeric_context"]) == 3
    provider.mutate = grounded_output
    caplog.clear()
    explicit = dispatch(daycare_request())
    assert len(explicit.payload["outputs"][0]["evidence_ids"]) == 2
    assert "numeric_context_citation_bound" not in caplog.text
    assert len(provider.calls) == 2


@pytest.mark.parametrize("mutation", ["unknown", "wrong_source", "same_number", "changed_number",
    "changed_unit", "fragment", "quote_whitespace", "id_whitespace", "no_parent", "no_support",
    "numeric_text", "numeric_item", "invalid_kind", "invalid_constraint", "duplicates"])
def test_invalid_inputs_still_fail_with_one_http_call(monkeypatch, mutation):
    def invalid(raw, data):
        missing_local(raw, data)
        statement = raw["outputs"][0]
        context = statement["numeric_context"][1]
        if mutation == "unknown": context["support_id"] = "evd_unknown"
        elif mutation == "wrong_source": context["support_id"] = statement["numeric_context"][0]["support_id"]
        elif mutation == "same_number": context["quote"] = "Прибыль составит 30 000 рублей."
        elif mutation == "changed_number": context["quote"] = PRICE.replace("30 000", "31 000")
        elif mutation == "changed_unit": context["quote"] = PRICE.replace("рублей", "долларов")
        elif mutation == "fragment": context["quote"] = "30 000 рублей"
        elif mutation == "quote_whitespace": context["quote"] = " " + PRICE + " "
        elif mutation == "id_whitespace": context["support_id"] = " " + context["support_id"] + " "
        elif mutation in ("no_parent", "no_support"):
            statement["parent_claim_ids"] = []
            if mutation == "no_parent":
                statement["evidence_ids"] = [statement["numeric_context"][0]["support_id"]]
        elif mutation == "numeric_text": statement["text"] = PRICE
        elif mutation == "numeric_item": statement["items"] = [AGE]
        elif mutation == "invalid_kind": statement["kind"] = "OBSERVATION"
        elif mutation == "invalid_constraint":
            target = next(s for s in raw["outputs"] if s["output_name"] == "main_growth_constraint")
            target["items"] *= 2
        elif mutation == "duplicates": statement["parent_claim_ids"] *= 2
    provider = NumericProvider(invalid)
    install_transport(monkeypatch, provider)
    with pytest.raises(ExecutorOutputError):
        dispatch(daycare_request())
    assert len(provider.calls) == 1


@pytest.mark.parametrize("family", ["local", "parent"])
def test_out_of_scope_id_cannot_be_recovered_by_quote_matching(monkeypatch, family):
    excluded = fact("private_price", PRICE, authorized=False)
    parent = positioning()
    claim = replace(parent.normalized_result.claims[0], claim_id="clm_excluded", value=PRICE,
                    authority_status=AuthorityStatus.OUT_OF_SCOPE)
    rejected = replace(parent, payload=plain(parent.payload),
                       normalized_result=replace(parent.normalized_result, result_id="res_excluded", claims=(claim,)))
    req = request(ModuleId.VIRTUAL_CMO, facts=(*daycare_facts(), excluded),
        upstream=upstream(positioning(), rejected) if family == "parent" else upstream(positioning()))
    from app.module_execution.executors.common import stable_id
    identity = stable_id("evd", req, "fact", excluded.fact_id) if family == "local" else claim.claim_id
    def invalid(raw, data):
        missing_local(raw, data)
        raw["outputs"][0]["numeric_context"][1]["support_id"] = identity
    provider = NumericProvider(invalid)
    install_transport(monkeypatch, provider)
    with pytest.raises(ExecutorOutputError):
        dispatch(req)
    assert len(provider.calls) == 1


@pytest.mark.parametrize("field", ["evidence_ids", "parent_claim_ids"])
def test_full_reference_array_is_never_truncated_or_overfilled(monkeypatch, field):
    parents = [positioning()]
    base = parents[0].normalized_result.claims[0]
    claims = tuple(replace(base, claim_id=f"clm_parent_{i}", value=PRICE) for i in range(33))
    parent = replace(parents[0], payload=plain(parents[0].payload),
                     normalized_result=replace(parents[0].normalized_result, claims=claims))
    facts = (*daycare_facts(), *(fact(f"extra_{i}", PRICE) for i in range(33)))
    req = request(ModuleId.VIRTUAL_CMO, facts=facts, upstream=upstream(parent))
    def full(raw, data):
        statement = raw["outputs"][0]
        refs = ([e["evidence_id"] for e in data["local_evidence"] if e["input_key"].startswith("extra_")]
                if field == "evidence_ids" else data["allowed_parent_claim_ids"])
        statement[field] = refs[:32]
        statement["numeric_context"] = [dict(support_id=refs[32], quote=PRICE)]
    provider = NumericProvider(full)
    install_transport(monkeypatch, provider)
    with pytest.raises(ExecutorOutputError):
        dispatch(req)
    assert len(provider.calls) == 1


def test_parent_binding_site_attribution_and_confidence_ceiling(monkeypatch):
    from app.module_execution.executors.claim_support import StrategyClaim, StoredNumericContext
    parent = positioning()
    base = parent.normalized_result.claims[0]
    numeric = replace(base, claim_id="clm_numeric_parent", confidence=Confidence.LOW, value=StrategyClaim(
        summary="Гипотеза спроса.", items=["Проверить спрос."], numeric_context=[
            StoredNumericContext(support_id="evd_previous", quote=PRICE, attribution="site_claim")]).model_dump_json())
    parent = replace(parent, payload=plain(parent.payload),
                     normalized_result=replace(parent.normalized_result, claims=(base, numeric)))
    req = request(ModuleId.VIRTUAL_CMO, facts=daycare_facts(), upstream=upstream(parent))
    def missing(raw, data):
        statement = raw["outputs"][0]
        sid = next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"] == "site_claim")
        statement.update(evidence_ids=[], parent_claim_ids=[base.claim_id], confidence="HIGH",
            numeric_context=[dict(support_id=sid, quote=daycare_facts()[-1].value),
                             dict(support_id=numeric.claim_id, quote=PRICE)])
    provider = NumericProvider(missing)
    install_transport(monkeypatch, provider)
    result = dispatch(req)
    statement = result.payload["outputs"][0]
    assert statement["parent_claim_ids"] == (base.claim_id, numeric.claim_id)
    claim = result.normalized_result.claims[0]
    assert claim.confidence is Confidence.LOW
    assert [c["attribution"] for c in json.loads(claim.value)["numeric_context"]] == ["site_claim", "site_claim"]
    assert len(provider.calls) == 1


def test_numeric_parent_cannot_supply_the_missing_required_strategic_parent(monkeypatch):
    parent = positioning()
    claim = replace(parent.normalized_result.claims[0], value=PRICE)
    parent = replace(parent, payload=plain(parent.payload),
                     normalized_result=replace(parent.normalized_result, claims=(claim,)))
    req = request(ModuleId.VIRTUAL_CMO, facts=daycare_facts(), upstream=upstream(parent))
    def missing(raw, data):
        raw["outputs"][0].update(parent_claim_ids=[], numeric_context=[
            dict(support_id=claim.claim_id, quote=PRICE)])
    provider = NumericProvider(missing)
    install_transport(monkeypatch, provider)
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(req)
    assert caught.value.stage.value == "schema_invalid"
    assert len(provider.calls) == 1


def test_helper_preserves_raw_fields_and_is_idempotent_and_no_cross_source_search():
    req = daycare_request()
    # Use synthetic raw JSON independent of Pydantic's whitespace coercion.
    local = {e.record.evidence_id: e for e in first_party_evidence(req, scoped_facts(req))}
    identity = next(eid for eid, e in local.items() if e.input_key == "product_truth")
    raw = dict(outputs=[dict(output_name="strategic_diagnosis", text="Гипотеза спроса.", items=["Проверить."],
        kind="HYPOTHESIS", confidence="HIGH", evidence_ids=[], parent_claim_ids=list(parent_claims(req)),
        numeric_context=[dict(support_id=identity, quote=PRICE)])], assumptions=[], limitations=[])
    before = deepcopy(raw)
    bound, count = bind_numeric_context_citations(raw, local, parent_claims(req))
    assert count == 1 and raw == before
    expected = deepcopy(before)
    expected["outputs"][0]["evidence_ids"] = [identity]
    assert bound == expected  # text, quote, support_id, kind, confidence all unchanged
    again, count = bind_numeric_context_citations(bound, local, parent_claims(req))
    assert again is bound and count == 0
    for identity in ("unknown", "evd_wrong", "evd_collision"):
        wrong = deepcopy(raw)
        wrong["outputs"][0]["numeric_context"][0]["support_id"] = identity
        sources = {**local, "evd_wrong": SimpleNamespace(value=AGE), "evd_collision": SimpleNamespace(value=PRICE)}
        parents = {**parent_claims(req), "evd_collision": SimpleNamespace(value=PRICE)}
        unchanged, count = bind_numeric_context_citations(wrong, sources, parents)
        assert unchanged is wrong and count == 0


def test_disabled_retains_uncited_rejection_and_entire_provider_wire(monkeypatch):
    req = daycare_request()
    provider = NumericProvider(missing_local)
    install_transport(monkeypatch, provider)
    with pytest.raises(ExecutorOutputError):
        dispatch(req, enabled=False)
    class PriorPolicy(VirtualCMOExecutor):
        def normalize_output_payload(self, request, payload, evidence, parents):
            return payload
    with pytest.raises(ExecutorOutputError):
        asyncio.run(PriorPolicy(model_call=production_model_call).execute(req))
    assert provider.calls[0] == provider.calls[1]
    assert len(provider.calls) == 2
