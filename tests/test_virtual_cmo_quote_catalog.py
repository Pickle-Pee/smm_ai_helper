"""Closed numeric diagnostics and optional advice through the real provider boundary."""
import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace
import traceback

import httpx
import pytest

from app.config import Settings
from app.marketing_orchestrator.quality_gates import QualityGateEvaluator
from app.marketing_orchestrator.quality_gates.contracts import AuthorityStatus, EvaluationBatch
from app.module_execution.executors import build_module_executor_registry
from app.module_execution.executors.common import (
    ExecutorOutputError, NumericContextFailureReason, NumericLocation, SemanticRule,
    StatementSemanticsError, first_party_evidence, parent_claims, plain, scoped_facts,
)
from app.module_execution.executors.intelligence_schemas import NumericContext, OtherStrategyStatement, StrategyOutput
from app.module_execution.executors.numeric_grounding import (
    MAX_NUMERIC_QUOTE_CATALOG_BYTES, MAX_NUMERIC_QUOTE_CATALOG_ENTRIES,
    context_units, numeric_quote_catalog, parent_context_units, validate_numeric_context,
)
from app.module_execution.executors.support_schema import support_response_schema
from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
from app.module_registry import ModuleId
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.worker import transient
from tests.test_graph_model_adapter import install_transport
from tests.test_module_executors import analyzer, fact, request
from tests.test_strategy_intelligence import IntelligenceModel, positioning, upstream, valid_request
from tests.test_virtual_cmo_numeric_grounding import AGE, PRICE, daycare_request, grounded_output


class NumericProvider:
    """Capture actual serialized requests; no monkeypatch of executor or adapter."""

    def __init__(self, mutate=None):
        self.calls = []
        self.mutate = mutate

    def __call__(self, req):
        self.calls.append(req.content)
        body = json.loads(req.content)
        data = json.loads(body["input"][1]["content"])
        raw = dict(outputs=[dict(output_name=name, kind="HYPOTHESIS", confidence="MEDIUM",
            text="Проверить влияние форматов посещения на спрос.", items=["Проверить спрос."],
            evidence_ids=[e["evidence_id"] for e in data["local_evidence"]][:8],
            parent_claim_ids=data["allowed_parent_claim_ids"][:8], numeric_context=[])
            for name in data["expected_outputs"]], assumptions=[], limitations=[])
        if self.mutate:
            self.mutate(raw, data)
        return httpx.Response(200, json={"status": "completed", "output_text": json.dumps(raw)})


def execute(executor, req=None):
    return asyncio.run(executor.execute(req or daycare_request()))


def gate(result, req):
    return QualityGateEvaluator().evaluate(EvaluationBatch(batch_id="bat_quote_catalog",
        results=tuple(u.result.normalized_result for u in req.upstream_results)
        + (result.normalized_result,)))


def numeric_statement(support_id="evd_local", quote=PRICE, **changes):
    data = dict(output_name="strategic_diagnosis", text="Качественная гипотеза.",
        items=["Проверить спрос."], kind="HYPOTHESIS", confidence="MEDIUM",
        evidence_ids=[support_id], parent_claim_ids=[],
        numeric_context=[NumericContext.model_construct(support_id=support_id, quote=quote)])
    data.update(changes)
    return OtherStrategyStatement.model_construct(**data)


@pytest.mark.parametrize("reason,statement,local,parents", [
    ("other_numeric_context_invalid", numeric_statement(quote=None),
        {"evd_local": SimpleNamespace(value=PRICE)}, {}),
    ("support_not_found", numeric_statement(), {}, {}),
    ("support_not_cited", numeric_statement(evidence_ids=["evd_other"]),
        {"evd_local": SimpleNamespace(value=PRICE)}, {}),
    ("support_not_cited", numeric_statement(evidence_ids=[], parent_claim_ids=["evd_local"]),
        {"evd_local": SimpleNamespace(value=PRICE)}, {}),
    ("source_has_no_eligible_quote", numeric_statement(),
        {"evd_local": SimpleNamespace(value={"price": 30000, "age": "2"})}, {}),
    ("quote_is_fragment", numeric_statement(quote="30 000 рублей"),
        {"evd_local": SimpleNamespace(value=PRICE)}, {}),
    ("quote_not_exact", numeric_statement(quote=PRICE.replace("30 000", "31 000")),
        {"evd_local": SimpleNamespace(value=PRICE)}, {}),
    ("quote_not_exact", numeric_statement(quote=PRICE.replace("рублей", "долларов")),
        {"evd_local": SimpleNamespace(value=PRICE)}, {}),
    ("quote_not_exact", numeric_statement(quote=PRICE.replace("30 000", "30000")),
        {"evd_local": SimpleNamespace(value=PRICE)}, {}),
])
def test_closed_numeric_reasons_match_the_actual_failed_condition(reason, statement, local, parents):
    with pytest.raises(StatementSemanticsError) as caught:
        validate_numeric_context(statement, local, parents)
    error = caught.value
    assert error.rule is SemanticRule.NUMERICAL_SUPPORT_REQUIRED
    assert error.numeric_location is NumericLocation.CONTEXT
    assert error.numeric_context_reason is NumericContextFailureReason(reason)
    assert error.numeric_context_index == 0
    assert not transient(error)
    assert PRICE not in str(error) and "evd_local" not in str(error)


def test_unknown_identity_precedes_uncited_and_direct_bypass_stays_fail_closed():
    with pytest.raises(StatementSemanticsError) as caught:
        validate_numeric_context(numeric_statement(evidence_ids=[]), {}, {})
    assert caught.value.numeric_context_reason is NumericContextFailureReason.SUPPORT_NOT_FOUND


def test_exact_full_values_accepted_and_qualifiers_are_not_normalized():
    quote = 'Цена 30 000 рублей; условие: "только полный день".\nБез скидки.'
    local = {"evd_local": SimpleNamespace(value={"pricing": quote})}
    validate_numeric_context(numeric_statement(quote=quote), local, {})
    with pytest.raises(StatementSemanticsError) as caught:
        validate_numeric_context(numeric_statement(quote=quote.split("\n")[0]), local, {})
    assert caught.value.numeric_context_reason is NumericContextFailureReason.QUOTE_IS_FRAGMENT


def test_catalog_is_sorted_deduplicated_exact_and_uses_authoritative_units():
    values = {"evd_b": {"repeated": [PRICE, PRICE], "nested": {"age": AGE}, "scalar": 12},
              "evd_a": 'Цена 20 рублей; "условие".\nДоставка отдельно.'}
    local = {identity: SimpleNamespace(value=value) for identity, value in values.items()}
    parents = {"clm_parent": SimpleNamespace(value="Гипотеза: спрос вырастет на 20%.")}
    expected = sorted({(identity, quote) for identity, value in values.items()
                       for quote in context_units(value)} |
                      {("clm_parent", quote) for quote in parent_context_units(parents["clm_parent"].value)})
    catalog = numeric_quote_catalog(local, parents)
    assert catalog == [dict(support_id=identity, exact_quote=quote) for identity, quote in expected]
    assert numeric_quote_catalog(dict(reversed(list(local.items()))), parents) == catalog
    assert json.loads(json.dumps(catalog, ensure_ascii=False)) == catalog


def test_catalog_empty_bare_numbers_oversized_and_untrimmed_leaves():
    values = [30000, "30000", " 20 рублей", "20 рублей ", "x" * 1000 + "2", {"x": [None, False]}]
    assert numeric_quote_catalog({"evd_empty": SimpleNamespace(value=values)}, {}) == []
    assert numeric_quote_catalog({}, {}) == []
    full = "2 " + "я" * 998
    assert numeric_quote_catalog({"evd_full": SimpleNamespace(value=full)}, {}) == [
        dict(support_id="evd_full", exact_quote=full)]


@pytest.mark.parametrize("long", [False, True])
def test_catalog_bounds_entries_and_utf8_json_bytes_without_truncation(long):
    local = {f"evd_{i:03}": SimpleNamespace(value=f"Цена {i} рублей; " + ("я" * 900 if long else "условие."))
             for i in range(90)}
    catalog = numeric_quote_catalog(local, {})
    assert MAX_NUMERIC_QUOTE_CATALOG_ENTRIES == 64
    assert MAX_NUMERIC_QUOTE_CATALOG_BYTES == 16384
    assert len(catalog) <= MAX_NUMERIC_QUOTE_CATALOG_ENTRIES
    assert len(json.dumps(catalog, ensure_ascii=False).encode("utf-8")) <= MAX_NUMERIC_QUOTE_CATALOG_BYTES
    assert catalog
    if long:
        assert len(catalog) < MAX_NUMERIC_QUOTE_CATALOG_ENTRIES
    else:
        assert len(catalog) == MAX_NUMERIC_QUOTE_CATALOG_ENTRIES
    assert [(r["support_id"], r["exact_quote"]) for r in catalog] == sorted(
        (r["support_id"], r["exact_quote"]) for r in catalog)
    assert all(r["exact_quote"] == local[r["support_id"]].value for r in catalog)
    assert numeric_quote_catalog(dict(reversed(list(local.items()))), {}) == catalog


def test_structured_parents_and_owned_site_metadata_never_become_quote_channels():
    from app.module_execution.executors.claim_support import StrategyClaim, StoredNumericContext
    inherited = StrategyClaim(summary="Качественный вывод.", items=["Проверить спрос."],
        numeric_context=[StoredNumericContext(support_id="evd_historical", quote=PRICE,
                                             attribution="site_claim")]).model_dump_json()
    site = {"trust": "site_claim", "site_states": [AGE], "evidence_id": "evd_secret123",
            "owner_confirmed": "Скрыто 99 рублей", "metadata": "Оценка 88 процентов"}
    rows = numeric_quote_catalog({"evd_site": SimpleNamespace(value=site)},
        {"clm_parent": SimpleNamespace(value=inherited),
         "clm_malformed": SimpleNamespace(value='{"related_claim_id":"clm_internal123"}')})
    assert rows == [dict(support_id="clm_parent", exact_quote=PRICE),
                    dict(support_id="evd_site", exact_quote=AGE)]
    assert inherited not in str(rows) and "clm_internal123" not in str(rows)


def test_disabled_full_http_bytes_equal_prefeature_hook_and_enabled_is_data_only(monkeypatch):
    class OriginalInputExecutor(VirtualCMOExecutor):
        def model_input_for(self, request, data, evidence, parents):
            return data

    provider = NumericProvider(grounded_output)
    install_transport(monkeypatch, provider)
    req = daycare_request()
    baseline = execute(OriginalInputExecutor(model_call=production_model_call), req)
    disabled = execute(VirtualCMOExecutor(model_call=production_model_call,
                                         numeric_quote_catalog_enabled=False), req)
    enabled = execute(VirtualCMOExecutor(model_call=production_model_call,
                                        numeric_quote_catalog_enabled=True), req)
    assert len(provider.calls) == 3
    assert provider.calls[0] == provider.calls[1]
    off, on = (json.loads(content) for content in provider.calls[1:])
    old_data = json.loads(off["input"][1]["content"])
    new_data = json.loads(on["input"][1]["content"])
    assert set(new_data) - set(old_data) == {"numeric_quote_catalog", "numeric_quote_catalog_guidance"}
    guidance = new_data.pop("numeric_quote_catalog_guidance")
    catalog = new_data.pop("numeric_quote_catalog")
    assert isinstance(guidance, str) and guidance
    assert new_data == old_data
    evidence = first_party_evidence(req, scoped_facts(req))
    local = {e.record.evidence_id: e for e in evidence}
    assert catalog == numeric_quote_catalog(local, parent_claims(req))
    assert len(json.dumps(catalog, ensure_ascii=False).encode()) <= MAX_NUMERIC_QUOTE_CATALOG_BYTES
    on["input"][1]["content"] = off["input"][1]["content"]
    assert on == off
    assert baseline == disabled == enabled
    assert gate(baseline, req) == gate(enabled, req)
    assert "numeric_quote_catalog" not in json.dumps(plain(enabled.payload))
    assert "numeric_quote_catalog_guidance" not in str(enabled.normalized_result)
    expected_schema = support_response_schema(StrategyOutput, local, parent_claims(req),
        requirement=VirtualCMOExecutor(model_call=None).support_requirement_for(req))
    from app.module_execution.executors.cmo_provider_contract import cmo_provider_schema
    assert off["text"]["format"]["schema"] == cmo_provider_schema(expected_schema, catalog)
    assert on["max_output_tokens"] == off["max_output_tokens"] == 16000


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("mutation,stage,reason", [
    ("fragment", "statement_semantics_invalid", "quote_is_fragment"),
    ("changed_number", "statement_semantics_invalid", "quote_not_exact"),
    ("changed_units", "statement_semantics_invalid", "quote_not_exact"),
    ("empty_source", "statement_semantics_invalid", "source_has_no_eligible_quote"),
    ("unknown", "schema_invalid", None),
    ("extra", "schema_invalid", None),
    ("text_number", "statement_semantics_invalid", None),
    ("no_support", "schema_invalid", None),
    ("too_many_contexts", "schema_invalid", None),
])
def test_advice_does_not_weaken_server_validation_and_safe_indexed_failure(
        monkeypatch, caplog, enabled, mutation, stage, reason):
    from app.module_execution.executors.common import log
    monkeypatch.setattr(log, "disabled", False)
    def mutate(raw, data):
        grounded_output(raw, data)
        statement = raw["outputs"][2]
        statement.update(evidence_ids=list(raw["outputs"][0]["evidence_ids"]),
                         numeric_context=list(raw["outputs"][0]["numeric_context"]))
        context = dict(statement["numeric_context"][1])
        statement["numeric_context"][1] = context
        if mutation == "fragment": context["quote"] = "30 000 рублей"
        elif mutation == "changed_number": context["quote"] = PRICE.replace("30 000", "31 000")
        elif mutation == "changed_units": context["quote"] = PRICE.replace("рублей", "долларов")
        elif mutation == "empty_source":
            identity = next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"] == "product")
            context["support_id"] = identity
            statement["evidence_ids"].append(identity)
        elif mutation == "unknown": context["support_id"] = "evd_invented_private123"
        elif mutation == "extra": statement["private_field"] = "private customer payload"
        elif mutation == "text_number": statement["text"] = "Конверсия 20%"
        elif mutation == "no_support": statement.update(evidence_ids=[], parent_claim_ids=[])
        elif mutation == "too_many_contexts": statement["numeric_context"] *= 2
    provider = NumericProvider(mutate)
    install_transport(monkeypatch, provider)
    with pytest.raises(ExecutorOutputError) as caught:
        execute(VirtualCMOExecutor(model_call=production_model_call,
                                    numeric_quote_catalog_enabled=enabled))
    assert len(provider.calls) == 1
    error = caught.value
    assert error.stage.value == stage and not transient(error)
    if reason:
        assert isinstance(error, StatementSemanticsError)
        assert error.rule is SemanticRule.NUMERICAL_SUPPORT_REQUIRED
        assert error.numeric_context_reason is NumericContextFailureReason(reason)
        assert error.output_index == 2 and error.numeric_context_index == 1
        assert f"reason={reason}" in caplog.text
    safe = caplog.text + str(error) + "".join(traceback.format_exception(error))
    wire = json.loads(provider.calls[0])
    data = json.loads(wire["input"][1]["content"])
    for secret in (PRICE, AGE, "31 000", "20%", "private customer payload", "evd_invented_private123",
                   *(e["evidence_id"] for e in data["local_evidence"]), *data["allowed_parent_claim_ids"]):
        assert secret not in safe
    assert error.__suppress_context__


def test_enabled_empty_catalog_is_valid_and_does_not_invent_numeric_context(monkeypatch):
    provider = NumericProvider()
    install_transport(monkeypatch, provider)
    req = request(ModuleId.VIRTUAL_CMO, facts=(fact("business_goal", "Рост спроса"),
                                             fact("product", "Частный детский сад")))
    result = execute(VirtualCMOExecutor(model_call=production_model_call,
                                        numeric_quote_catalog_enabled=True), req)
    assert len(provider.calls) == 1
    data = json.loads(json.loads(provider.calls[0])["input"][1]["content"])
    assert data["numeric_quote_catalog"] == []
    assert all(not statement["numeric_context"] for statement in result.payload["outputs"])


def test_catalog_only_contains_request_authorized_facts_and_accepted_scoped_parents(monkeypatch):
    private = "Приватный источник 99 рублей"
    excluded = "Непринятый родитель 88 процентов"
    parent = positioning()
    parent = replace(parent, payload=plain(parent.payload), normalized_result=replace(parent.normalized_result,
        claims=(replace(parent.normalized_result.claims[0], value=excluded,
                        authority_status=AuthorityStatus.OUT_OF_SCOPE),)))
    req = request(ModuleId.VIRTUAL_CMO, facts=(*daycare_request().context_packet.known_facts,
                  fact("private", private, authorized=False)), upstream=upstream(parent))
    provider = NumericProvider()
    install_transport(monkeypatch, provider)
    execute(VirtualCMOExecutor(model_call=production_model_call, numeric_quote_catalog_enabled=True), req)
    data = json.loads(json.loads(provider.calls[0])["input"][1]["content"])
    catalog = data["numeric_quote_catalog"]
    assert private not in str(data) and excluded not in str(catalog)
    assert all(row["support_id"].startswith("evd_") for row in catalog)
    assert not data["allowed_parent_claim_ids"]


def test_site_and_structured_parent_attribution_stays_unconfirmed_with_advice(monkeypatch):
    from app.module_execution.executors.claim_support import StrategyClaim, StoredNumericContext
    parent = positioning()
    claim = replace(parent.normalized_result.claims[0], value=StrategyClaim(
        summary="Качественная гипотеза.", items=["Проверить спрос."],
        numeric_context=[StoredNumericContext(support_id="evd_old", quote=PRICE,
                                              attribution="site_claim")]).model_dump_json())
    parent = replace(parent, payload=plain(parent.payload), normalized_result=replace(parent.normalized_result, claims=(claim,)))
    site = dict(trust="site_claim", site_states=[AGE], internal_id="evd_internal123")
    req = request(ModuleId.VIRTUAL_CMO, facts=(fact("business_goal", "Рост спроса"),
        fact("product", "Частный детский сад"), fact("site_claim", site)), upstream=upstream(parent))
    def inherited(raw, data):
        sid = next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"] == "site_claim")
        raw["outputs"][0]["numeric_context"] = [dict(support_id=sid, quote=AGE),
                                                dict(support_id=claim.claim_id, quote=PRICE)]
    provider = NumericProvider(inherited)
    install_transport(monkeypatch, provider)
    result = execute(VirtualCMOExecutor(model_call=production_model_call,
                                        numeric_quote_catalog_enabled=True), req)
    contexts = json.loads(result.normalized_result.claims[0].value)["numeric_context"]
    assert [context["attribution"] for context in contexts] == ["site_claim", "site_claim"]
    assert gate(result, req).synthesis_manifest.accepted_claim_ids
    assert len(provider.calls) == 1


@pytest.mark.parametrize("module", [ModuleId.POSITIONING, ModuleId.EXPERIMENTS])
def test_catalog_flag_cannot_change_other_module_model_arguments(module):
    calls = []
    for enabled in (False, True):
        model = IntelligenceModel(use_parents=True)
        registry = build_module_executor_registry(model_call=model, analyzer=analyzer(),
            registry_version="1.3.0", virtual_cmo_numeric_quote_catalog=enabled)
        req = request(module) if module is ModuleId.POSITIONING else valid_request(module)
        asyncio.run(registry.resolve(module.value.lower() + ".v1").execute(req))
        calls.append(model.calls)
    assert calls[0] == calls[1]


@pytest.mark.parametrize("positioning_enabled,experiments_enabled", [(False, True), (True, False), (True, True)])
def test_other_rollout_flags_cannot_enable_cmo_catalog(positioning_enabled, experiments_enabled):
    model = IntelligenceModel(use_parents=True)
    registry = build_module_executor_registry(model_call=model, analyzer=analyzer(), registry_version="1.3.0",
        positioning_schema_projection=positioning_enabled, experiments_schema_projection=experiments_enabled,
        virtual_cmo_numeric_quote_catalog=False)
    asyncio.run(registry.resolve("virtual_cmo.v1").execute(daycare_request()))
    assert len(model.calls) == 1
    data = json.loads(model.calls[0]["text"])
    assert "numeric_quote_catalog" not in data and "numeric_quote_catalog_guidance" not in data


def test_numeric_catalog_configuration_defaults_to_false():
    assert Settings.model_fields["VIRTUAL_CMO_NUMERIC_QUOTE_CATALOG_ENABLED"].default is False






def test_catalog_excludes_nul_and_non_utf8_units_without_changing_context_rules():
    nul_quote = "Price 20 dollars\x00 includes tax"
    surrogate_quote = "Price 20 dollars\ud800 includes tax"
    assert list(context_units(nul_quote)) == [nul_quote]
    assert list(context_units(surrogate_quote)) == [surrogate_quote]
    assert numeric_quote_catalog({
        "evd_nul": SimpleNamespace(value=nul_quote),
        "evd_surrogate": SimpleNamespace(value=surrogate_quote),
        "evd_bad\x00": SimpleNamespace(value=PRICE),
        "evd_valid": SimpleNamespace(value=PRICE),
    }, {}) == [dict(support_id="evd_valid", exact_quote=PRICE)]


@pytest.mark.parametrize("changes", [
    {"numeric_context_reason": "quote_not_exact"},
    {"output_index": -1}, {"output_index": True}, {"numeric_context_index": -1},
    {"numeric_context_index": 1.0},
])
def test_diagnostics_only_accept_closed_server_codes_and_zero_based_indices(changes):
    with pytest.raises(TypeError):
        StatementSemanticsError(SemanticRule.NUMERICAL_SUPPORT_REQUIRED,
                                numeric_location=NumericLocation.CONTEXT, **changes)
