"""Offline observations at the actual rejection boundary; no production access."""
import asyncio
from dataclasses import replace
import json
import logging
from types import SimpleNamespace
import traceback
from unittest.mock import AsyncMock

import pytest

from app.marketing_orchestrator.quality_gates.contracts import AuthorityStatus
from app.module_execution import ModuleExecutorRegistry
from app.module_execution.executors import numeric_diagnostics as diagnostics
from app.module_execution.executors.common import (
    ExecutorOutputError, NumericContextFailureReason, NumericLocation,
    OutputFailureStage, SemanticRule, StatementSemanticsError,
)
from app.module_execution.executors.intelligence_schemas import StrategyOutput
from app.module_execution.executors.numeric_grounding import validate_numeric_context
from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
from app.module_registry import ModuleId, ModuleResultStatus
from app.orchestration_runtime.contracts import GraphWorkItem
from app.orchestration_runtime.worker import ModuleGraphWorker
from app.orchestration_runtime.serialization import result_to_json
from tests.test_module_executors import fact, request
from tests.test_strategy_intelligence import IntelligenceModel, positioning, upstream
from tests.test_virtual_cmo_quote_catalog import numeric_statement, gate

SOURCE = 'Цена 20 рублей; условие: "полный день".\nБез скидки.'
OTHER = "Цена 30 рублей; доставка отдельно."
PRIVATE = "PRIVATE_BUSINESS_TOKEN_123"


@pytest.fixture(autouse=True)
def logging_enabled(monkeypatch):
    for name in (diagnostics.log.name, "app.orchestration_runtime.worker",
                 "app.module_execution.executors.common"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", False)


def events(caplog):
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == diagnostics.log.name]


def req(identity="cmo.diagnostic", extra=(), parents=()):
    return request(ModuleId.VIRTUAL_CMO, identity=identity, outputs=("strategic_diagnosis",),
                   facts=(fact("business_goal", "Grow demand"), fact("product", {"price": SOURCE}),
                          fact("product_truth", OTHER), *extra), upstream=parents)


def model_for(quote, *, cited=True):
    model = IntelligenceModel()
    def change(raw, data):
        statement = raw["outputs"][0]
        identity = next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"] == "product")
        statement["evidence_ids"] = [identity] if cited else [data["local_evidence"][0]["evidence_id"]]
        statement["numeric_context"] = [dict(support_id=identity, quote=quote)]
        statement["parent_claim_ids"] = data["allowed_parent_claim_ids"][:8]
    model.change = change
    return model


def probe(quote, value=SOURCE, *, raw_quote=None, parents=None, evidence_ids=None):
    statement = numeric_statement(quote=quote)
    if evidence_ids is not None:
        statement.evidence_ids = evidence_ids
    output = SimpleNamespace(outputs=[statement])
    payload = {"outputs": [{"numeric_context": [{"quote": raw_quote if raw_quote is not None else quote}]}]}
    local = {"evd_local": SimpleNamespace(value=value)}
    error = StatementSemanticsError(SemanticRule.NUMERICAL_SUPPORT_REQUIRED,
        numeric_location=NumericLocation.CONTEXT, numeric_context_reason=NumericContextFailureReason.QUOTE_NOT_EXACT,
        output_index=0, numeric_context_index=0)
    return diagnostics.classify(payload, output, local, parents or {}, error)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("quote,reason,field", [
    (OTHER, "quote_not_exact", "other_parsed_exact"),
    ("Цена 20 рублей", "quote_is_fragment", "selected_parsed_fragment"),
    (SOURCE.replace("\n", "\r\n"), "quote_not_exact", "selected_parsed_line_endings"),
    (SOURCE.replace("20 рублей", "21 рублей"), "quote_not_exact", None),
])
def test_actual_rejection_classified_without_acceptance_or_extra_calls(caplog, enabled, quote, reason, field):
    model = model_for(quote)
    with pytest.raises(StatementSemanticsError) as caught:
        asyncio.run(VirtualCMOExecutor(model_call=model, numeric_quote_catalog_enabled=enabled).execute(req()))
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    assert caught.value.numeric_context_reason.value == reason
    assert len(model.calls) == 1
    event, = events(caplog)
    assert event["reason"] == reason and event["execution_id"] == "cmo.diagnostic"
    assert event["output_index"] == event["numeric_context_index"] == 0
    assert event["catalog_enabled"] is enabled and event["scan_complete"]
    if field:
        assert event[field] == "match"
    assert quote not in caplog.text
    assert SOURCE not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("quote", [SOURCE, "  " + SOURCE + "  "])
def test_exact_and_current_whitespace_acceptance_and_gates_unchanged(caplog, enabled, quote):
    model = model_for(quote)
    executor = VirtualCMOExecutor(model_call=model, numeric_quote_catalog_enabled=enabled)
    result = asyncio.run(executor.execute(req()))
    assert result.payload["outputs"][0]["numeric_context"][0]["quote"] == SOURCE
    assert result.normalized_result.result_id in gate(result, req()).synthesis_manifest.accepted_result_ids
    baseline = VirtualCMOExecutor(model_call=model_for(quote), numeric_quote_catalog_enabled=enabled)
    baseline.observe_output_rejection = lambda *a: pytest.fail("observer ran on accepted output")
    expected = asyncio.run(baseline.execute(req()))
    assert result == expected
    assert not events(caplog) and len(model.calls) == 1


@pytest.mark.parametrize("reason", list(NumericContextFailureReason))
def test_every_reason_preserved_in_safe_event(caplog, reason):
    quote = None if reason is NumericContextFailureReason.OTHER_NUMERIC_CONTEXT_INVALID else (
        "Цена 20 рублей" if reason is NumericContextFailureReason.QUOTE_IS_FRAGMENT else OTHER)
    statement = numeric_statement(quote=quote)
    local = {"evd_local": SimpleNamespace(value=SOURCE)}
    if reason is NumericContextFailureReason.SUPPORT_NOT_FOUND:
        local = {}
    elif reason is NumericContextFailureReason.SUPPORT_NOT_CITED:
        statement.evidence_ids = []
    elif reason is NumericContextFailureReason.SOURCE_HAS_NO_ELIGIBLE_QUOTE:
        local["evd_local"].value = 20
    with pytest.raises(StatementSemanticsError) as caught:
        validate_numeric_context(statement, local, {})
    error = caught.value
    error.output_index = 0
    evidence = [SimpleNamespace(record=SimpleNamespace(evidence_id=k), value=v.value) for k, v in local.items()]
    diagnostics.observe(req(), {"outputs": [{"numeric_context": [{"quote": quote}]}]},
        SimpleNamespace(outputs=[statement]), evidence, {}, error, catalog_enabled=False)
    assert error.numeric_context_reason is reason
    event, = events(caplog)
    assert event["reason"] == reason.value
    if quote is None:
        assert not event["scan_complete"] and event["selected_parsed_exact"] == "not_checked"


@pytest.mark.parametrize("source,quote,field", [
    (SOURCE, "  " + SOURCE + "  ", "edge_whitespace"),
    (SOURCE, SOURCE.replace("\n", "\r\n"), "line_endings"),
    ("Café coûte 20 euros.", "Cafe\u0301 coûte 20 euros.", "nfc"),
    ("Цена 20 рублей.", "Цена\u00a020 рублей.", "nbsp"),
    (SOURCE, json.dumps(SOURCE, ensure_ascii=False)[1:-1], "json_escaping"),
    (SOURCE, json.dumps(SOURCE, ensure_ascii=True)[1:-1], "json_escaping"),
])
def test_closed_representation_differences_are_observations_only(source, quote, field):
    summary = probe(quote, source)
    assert summary.selected_parsed.exact is diagnostics.Observation.NO_MATCH
    assert getattr(summary.selected_parsed, field) is diagnostics.Observation.MATCH
    assert summary.scan_complete


def test_original_decoded_quote_not_pydantic_stripped_quote(caplog):
    quote = "  Цена 20 рублей  "
    model = model_for(quote)
    with pytest.raises(StatementSemanticsError):
        asyncio.run(VirtualCMOExecutor(model_call=model).execute(req()))
    event, = events(caplog)
    assert event["raw_equals_parsed"] is False
    assert event["selected_raw_fragment"] == "no_match"
    assert event["selected_parsed_fragment"] == "match"


@pytest.mark.parametrize("ascii_mode", [False, True])
def test_json_wire_escaping_preserves_decoded_equality(ascii_mode):
    raw = json.loads(json.dumps({"quote": SOURCE}, ensure_ascii=ascii_mode))["quote"]
    summary = probe(raw)
    assert summary.raw_equals_parsed
    assert summary.selected_raw.exact is diagnostics.Observation.MATCH
    assert summary.selected_raw.json_escaping is diagnostics.Observation.NO_MATCH


def test_conflicting_family_identity_observed_without_rebinding():
    summary = probe(OTHER, parents={"evd_local": SimpleNamespace(value=OTHER)})
    assert summary.source_family is diagnostics.SourceFamily.CONFLICT
    assert summary.selected_parsed.exact is diagnostics.Observation.NO_MATCH
    assert summary.other_parsed_exact is diagnostics.Observation.NO_MATCH
    statement = numeric_statement(quote=OTHER)
    with pytest.raises(StatementSemanticsError) as caught:
        validate_numeric_context(statement, {"evd_local": SimpleNamespace(value=SOURCE)},
                                 {"evd_local": SimpleNamespace(value=OTHER)})
    assert caught.value.numeric_context_reason is NumericContextFailureReason.QUOTE_NOT_EXACT


def test_site_metadata_and_serialized_parent_do_not_become_quote_channels():
    site = {"trust": "site_claim", "site_states": [SOURCE], "metadata": OTHER}
    assert probe(OTHER, site).selected_parsed.exact is diagnostics.Observation.NO_MATCH
    parent = json.dumps({"related_claim_id": OTHER})
    assert probe(OTHER, parents={"clm_other": SimpleNamespace(value=parent)}).other_parsed_exact is diagnostics.Observation.NO_MATCH


@pytest.mark.parametrize("excluded", ["unauthorized", "out_of_scope", "unaccepted"])
def test_only_authorized_request_sources_scanned(caplog, excluded):
    parent = positioning()
    claim = parent.normalized_result.claims[0]
    normalized = replace(parent.normalized_result, claims=(replace(claim, value=PRIVATE,
        authority_status=AuthorityStatus.OUT_OF_SCOPE if excluded == "out_of_scope" else claim.authority_status),))
    if excluded == "unaccepted":
        normalized = replace(normalized, module_status=ModuleResultStatus.FAIL)
    parent = replace(parent, payload=result_to_json(parent)["payload"], normalized_result=normalized)
    facts = (fact("private", PRIVATE, authorized=False),) if excluded == "unauthorized" else ()
    model = model_for(PRIVATE)
    with pytest.raises(StatementSemanticsError):
        asyncio.run(VirtualCMOExecutor(model_call=model).execute(req(extra=facts, parents=() if excluded == "unauthorized" else upstream(parent))))
    event, = events(caplog)
    assert event["other_parsed_exact"] == "no_match"
    assert PRIVATE not in caplog.text
    assert PRIVATE not in model.calls[0]["text"] or excluded == "out_of_scope"


@pytest.mark.parametrize("limit", ["MAX_UNITS", "MAX_NODES", "MAX_CHARACTERS", "MAX_DEPTH", "MAX_SOURCES"])
def test_bounded_scan_never_reports_false_negative(monkeypatch, limit):
    monkeypatch.setattr(diagnostics, limit, 0)
    summary = probe(OTHER, [SOURCE], parents={"clm_other": SimpleNamespace(value=OTHER)})
    assert not summary.scan_complete
    assert summary.selected_parsed.exact is diagnostics.Observation.INCOMPLETE
    assert summary.other_parsed_exact is diagnostics.Observation.INCOMPLETE


def test_noneligible_nodes_and_deep_sources_are_bounded(monkeypatch):
    monkeypatch.setattr(diagnostics, "MAX_NODES", 8)
    summary = probe(OTHER, [0] * 10000)
    assert not summary.scan_complete and summary.units_scanned == 0
    value = SOURCE
    for _ in range(100):
        value = [value]
    assert not probe(OTHER, value).scan_complete


def test_selected_complete_while_other_scope_incomplete(monkeypatch):
    monkeypatch.setattr(diagnostics, "MAX_SOURCES", 1)
    summary = probe(SOURCE, parents={"clm_other": SimpleNamespace(value=OTHER)})
    assert summary.selected_parsed.exact is diagnostics.Observation.MATCH
    assert summary.other_parsed_exact is diagnostics.Observation.INCOMPLETE
    assert not summary.scan_complete


@pytest.mark.parametrize("failure", ["classifier", "logger", "hook"])
def test_diagnostic_exceptions_and_tracing_do_not_change_rejection(monkeypatch, caplog, failure):
    model = model_for(PRIVATE)
    executor = VirtualCMOExecutor(model_call=model)
    def broken(*args, **kwargs):
        raise RuntimeError(PRIVATE + " api_key secret evd_support")
    if failure == "classifier":
        monkeypatch.setattr(diagnostics, "classify", broken)
    elif failure == "logger":
        monkeypatch.setattr(diagnostics.log, "warning", broken)
    else:
        monkeypatch.setattr(executor, "observe_output_rejection", broken)
    with pytest.raises(StatementSemanticsError) as caught:
        asyncio.run(executor.execute(req()))
    assert caught.value.numeric_context_reason is NumericContextFailureReason.QUOTE_NOT_EXACT
    assert len(model.calls) == 1
    assert PRIVATE not in caplog.text
    assert PRIVATE not in "".join(traceback.format_exception(caught.value))
    for record in caplog.records:
        assert record.exc_info is None and record.stack_info is None
        assert PRIVATE not in repr(record.__dict__)
    if failure == "classifier":
        event, = events(caplog)
        assert not event["scan_complete"] and event["other_parsed_exact"] == "not_checked"


@pytest.mark.parametrize("location", ["text", "items"])
def test_numeric_qualitative_fields_keep_original_reason_without_quote_probe(caplog, location):
    model = IntelligenceModel()
    model.change = lambda raw, data: raw["outputs"][0].update({location: PRIVATE if location == "text" else [PRIVATE]})
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(VirtualCMOExecutor(model_call=model).execute(req()))
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    event, = events(caplog)
    assert event["reason"] is None and event["location"] == location
    assert event["selected_raw_exact"] == "not_checked"


def test_earlier_schema_failure_not_reclassified(caplog):
    model = model_for(OTHER)
    change = model.change
    def invalid(raw, data):
        change(raw, data)
        raw["outputs"][0]["numeric_context"][0]["support_id"] = "unknown"
    model.change = invalid
    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(VirtualCMOExecutor(model_call=model).execute(req()))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID
    assert not events(caplog) and len(model.calls) == 1


def test_concurrent_graph_failures_use_actual_job_identity_and_terminal_lifecycle(caplog):
    async def exercise():
        model = model_for(OTHER)
        executor = VirtualCMOExecutor(model_call=model)
        original = model.__class__.__call__
        # Give both executions an opportunity to overlap on a shared executor.
        class ConcurrentModel(IntelligenceModel):
            async def __call__(self, **kwargs):
                await asyncio.sleep(0)
                return await original(self, **kwargs)
        concurrent = ConcurrentModel()
        concurrent.change = model.change
        executor._model_call = concurrent
        services = []
        for i in range(2):
            item = GraphWorkItem(f"job.actual.{i}", f"run.actual.{i}", 1, "virtual_cmo", f"test-claim-{i}", 1)
            service = SimpleNamespace(lease_seconds=330, executors=ModuleExecutorRegistry(),
                claim=AsyncMock(return_value=item), load_work=AsyncMock(return_value=(object(), req(item.job_id))),
                fail=AsyncMock(), finish=AsyncMock())
            worker = ModuleGraphWorker(service)
            async def dispatch(binding, request):
                return await executor.execute(request)
            worker.dispatcher.dispatch = dispatch
            services.append((worker, service, item))
        assert await asyncio.gather(*(w.once() for w, _, _ in services)) == [True, True]
        for _, service, item in services:
            service.fail.assert_awaited_once_with(item, code="execution_invalid", retryable=False)
            service.finish.assert_not_awaited()
        assert len(concurrent.calls) == 2
    asyncio.run(exercise())
    assert {e["execution_id"] for e in events(caplog)} == {"job.actual.0", "job.actual.1"}
    for i in range(2):
        assert f"run_id=run.actual.{i} job_id=job.actual.{i}" in caplog.text


def test_oversized_local_map_falls_back_before_touching_evidence(caplog):
    class ForbiddenEvidence:
        @property
        def record(self):
            pytest.fail("oversized map must not be copied")
    evidence = (ForbiddenEvidence(),) * (diagnostics.MAX_SOURCES + 1)
    error = StatementSemanticsError(SemanticRule.NUMERICAL_SUPPORT_REQUIRED,
        numeric_location=NumericLocation.CONTEXT,
        numeric_context_reason=NumericContextFailureReason.QUOTE_NOT_EXACT,
        output_index=0, numeric_context_index=0)
    diagnostics.observe(req(), None, None, evidence, {}, error, catalog_enabled=False)
    event, = events(caplog)
    assert not event["scan_complete"]
    assert event["source_family"] == event["citation"] == "not_checked"
    assert event["sources_scanned"] == event["units_scanned"] == 0
    assert event["other_raw_exact"] == "not_checked"
