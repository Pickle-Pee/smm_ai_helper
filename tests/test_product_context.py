"""Owned-page acquisition and internal Copilot regressions, all providers faked."""
import asyncio
import json
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError

from app.marketing_copilot.application_contracts import CopilotRequest, ResultKind
from app.marketing_copilot.context_resolver import ContextEntry, ContextResolver
from app.marketing_copilot.contracts import CopilotContractError, IntentKind
from app.marketing_copilot.factory import build_marketing_copilot_service
from app.marketing_orchestrator.quality_gates.contracts import EvidenceSourceClass
from app.module_execution import ModuleExecutionRequest
from app.module_execution.executors import CompetitorAnalysisExecutor, PositioningExecutor
from app.module_registry import ModuleId, ToolCapability
from app.product_context import (AcquisitionResult, ConfirmedBusinessFact, ExtractorUnavailableError, KnowledgeKind,
    OwnedProductSnapshot, OwnedProductEvidenceService, OwnedSiteRequest, ProductContextError,
    SnapshotField, SourceOutcome, TrustKind, build_owned_site_analyzer)
from app.product_context.projection import attach_acquisition, project_confirmation, project_snapshot
from tests.test_copilot_application import intent_model
from tests.test_module_executors import FakeModel, analyzer, fact
from tests.test_safe_http import Stream

OWN = "https://owned.example/product"
COMPETITOR = "https://competitor.example/page"
PRODUCT = "Acme is a scheduling service for busy teams."
AUDIENCE = "Designed for independent clinics and their staff."
JOB = "Reduce time spent arranging customer appointments."
PRICE = "Plans start at 19 EUR per month excluding tax."
LEADER = "We are №1 on the market according to our own survey."


def observation(field, text, **kwargs):
    return dict(field=field.value, kind="OBSERVATION", text=text, excerpts=[text], **kwargs)


def extraction(statements=None):
    return json.dumps({"statements": statements if statements is not None else [
        observation(SnapshotField.PRODUCT, PRODUCT), observation(SnapshotField.AUDIENCE, AUDIENCE),
        observation(SnapshotField.JOB, JOB), observation(SnapshotField.PRICING, PRICE),
        observation(SnapshotField.POSITIONING, LEADER),
    ]}, ensure_ascii=False)


def acquisition(*, raw=None, page=None, url=OWN):
    page = page if page is not None else {"ok": True, "url": url, "final_url": url,
        "title": "Acme", "main_text_excerpt": "\n".join([PRODUCT, AUDIENCE, JOB, PRICE, LEADER])}
    site = SimpleNamespace(analyze_url=AsyncMock(return_value=SimpleNamespace(url_summaries=[page])))
    model = AsyncMock(return_value=raw if raw is not None else extraction())
    svc = OwnedProductEvidenceService(analyzer=site, extractor=model)
    result = asyncio.run(svc.acquire(OwnedSiteRequest(owned_site_url=url)))
    return result, model, site


def entry(key, value):
    return ContextEntry(key, fact(key, value, scenario_relevance=frozenset({
        "strategy_builder_v1", "competitive_positioning_v1"})))


def request(**kwargs):
    return CopilotRequest(actor_id=1, request_id="owned-source-test", message="Build strategy", **kwargs)


def copilot(kind=IntentKind.MARKETING_STRATEGY, urls=()):
    graph = SimpleNamespace(start_compiled_run=AsyncMock())
    svc = build_marketing_copilot_service(intent_model=intent_model(kind, urls),
        module_model=FakeModel(), url_analyzer=analyzer(), market_analyzer=analyzer(),
        registry_version="1.2.0")
    svc.graph_service = graph
    return svc, graph


def test_snapshot_contract_literal_pricing_trust_and_no_model_ids():
    result, model, site = acquisition()
    assert result.outcome is SourceOutcome.ACQUIRED
    snapshot = result.snapshot
    assert snapshot.schema_version == "owned_product_snapshot.v1"
    assert snapshot.canonical_url == OWN and snapshot.page_title == "Acme"
    assert snapshot.trust is TrustKind.SITE_CLAIM
    assert all(e.record.source_class is EvidenceSourceClass.FIRST_PARTY for e in snapshot.evidence)
    assert all("not independently verified" in e.record.provenance for e in snapshot.evidence)
    assert OwnedProductSnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot
    assert AcquisitionResult.model_validate_json(result.model_dump_json()) == result
    with pytest.raises(ValidationError):
        snapshot.page_title = "changed"
    site.analyze_url.assert_awaited_once_with(OWN)
    call = model.call_args.kwargs
    assert call["instruction"].count("<!-- EXPERT_CORE:") == 1
    assert set(json.loads(call["text"])) == {"fetched_text"}
    schema = call["response_schema"]
    assert schema["additionalProperties"] is False
    for definition in schema["$defs"].values():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False
    assert "evidence_id" not in json.dumps(schema) and "statement_id" not in json.dumps(schema)
    assert acquisition()[0].snapshot == snapshot


def test_owned_url_and_goal_recover_descriptions_but_require_confirmation_before_start():
    result, _, _ = acquisition()
    req = attach_acquisition(request(current_request=(entry("business_goal", "Increase bookings"),)), result)
    svc, graph = copilot()
    output = asyncio.run(svc.execute(req))
    assert output.kind is ResultKind.NEEDS_INPUT
    assert set(output.clarification.alternatives[0]) == {"relevant_alternative", "product_truth"}
    graph.start_compiled_run.assert_not_awaited()
    facts = ContextResolver().resolve(owned_site_context=req.owned_site_context).project_context
    assert {f.label for f in facts} >= {"product", "target_or_target_hypothesis", "customer_job_or_need"}
    assert "product_truth" not in {f.label for f in facts}
    assert all(f.value["trust"] == "site_claim" for f in facts)
    leader = next(f for f in facts if f.label == "owned_site_positioning_message_observations")
    assert leader.value["site_states"] == (LEADER,)
    assert all("company is market leader" not in str(f.value) for f in facts)


def test_confirmation_is_separate_explicit_and_allows_strategy_start():
    acquired, _, _ = acquisition()
    snapshot = acquired.snapshot
    confirm = ConfirmedBusinessFact(snapshot_id=snapshot.snapshot_id,
        statement_ids=(snapshot.statements[0].statement_id,), confirmed_by="authorized-owner",
        confirmation_reference="caller-confirmation:123")
    truth = project_confirmation(snapshot, confirm)
    assert truth.fact.value["trust"] == "confirmed_business_fact"
    assert snapshot.trust is TrustKind.SITE_CLAIM
    req = attach_acquisition(request(current_request=(truth, entry("business_goal", "More appointments"),
        entry("relevant_alternative", "Manual spreadsheet scheduling"))), acquired)
    svc, graph = copilot()
    output = asyncio.run(svc.execute(req))
    assert output.kind is ResultKind.WORKFLOW_STARTED
    graph.start_compiled_run.assert_awaited_once()
    plan = graph.start_compiled_run.call_args.kwargs["plan"]
    assert [n.module_id for n in plan.nodes] == [ModuleId.POSITIONING, ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS]
    pos = plan.nodes[0]
    model = FakeModel()
    executor = PositioningExecutor(model_call=model)
    emitted = asyncio.run(executor.execute(ModuleExecutionRequest(execution_id="owned-pos", module_id=pos.module_id,
        objective=pos.objective, expected_outputs=pos.expected_outputs, context_packet=pos.context_packet)))
    assert emitted.normalized_result.claims
    data = json.loads(model.calls[0]["text"])
    product = next(e for e in data["local_evidence"] if e["input_key"] == "product")
    assert product["value"]["trust"] == "site_claim"
    assert product["value"]["evidence"][0]["record"]["source_class"] == "FIRST_PARTY"
    with pytest.raises(ProductContextError):
        project_confirmation(snapshot, confirm.model_copy(update={"snapshot_id": "owned_wrong"}))


def test_explicit_override_and_all_layer_precedence_preserve_original_observation():
    acquired, _, _ = acquisition()
    site_entries = project_snapshot(acquired.snapshot)
    key = "target_or_target_hypothesis"
    resolver = ContextResolver()
    def resolve(current=(), owned=site_entries, project=(entry(key, "Project"),), brand=(entry(key, "Brand"),)):
        context = resolver.resolve(current_request=current, owned_site_context=owned, project_run=project,
            brand_profile=brand, conversation=(entry(key, "Conversation"),))
        return next((f for f in (*context.project_context, *context.known_facts) if f.label == key), None)
    assert resolve((entry(key, "B"),)).value == "B"
    assert resolve().value["site_states"] == (AUDIENCE,)
    assert resolve(owned=()).value == "Project"
    assert resolve(owned=(), project=()).value == "Brand"
    assert resolve(owned=(), project=(), brand=()).value == "Conversation"
    assert resolve((entry(key, ""),)) is None
    assert next(s.text for s in acquired.snapshot.statements if s.field is SnapshotField.AUDIENCE) == AUDIENCE


@pytest.mark.parametrize("kind", [IntentKind.MARKETING_STRATEGY, IntentKind.COMPARATIVE_POSITIONING])
def test_own_and_competitor_have_distinct_source_roles_and_evidence(kind):
    acquired, _, _ = acquisition()
    source_key = "competitor_urls" if kind is IntentKind.MARKETING_STRATEGY else "competitor_url"
    entries = (entry(source_key, [COMPETITOR] if source_key == "competitor_urls" else COMPETITOR),
        entry("business_goal", "Increase bookings"), entry("relevant_alternative", "Manual booking"),
        entry("product_truth", "Owner confirms appointment scheduling is supported"))
    req = attach_acquisition(request(current_request=entries,
        available_tools=frozenset({ToolCapability.SITE_FETCH})), acquired)
    req = replace(req, message=f"Compare our site {OWN} with competitor {COMPETITOR}")
    svc, graph = copilot(kind, urls=(OWN, COMPETITOR))
    output = asyncio.run(svc.execute(req))
    assert output.kind is ResultKind.WORKFLOW_STARTED
    plan = graph.start_compiled_run.call_args.kwargs["plan"]
    node = next(n for n in plan.nodes if n.module_id is ModuleId.COMPETITOR_ANALYSIS)
    site = analyzer()
    model = FakeModel()
    competitor = asyncio.run(CompetitorAnalysisExecutor(model_call=model, analyzer=site).execute(
        ModuleExecutionRequest(execution_id="competitor-exec", module_id=node.module_id,
            objective=node.objective, expected_outputs=node.expected_outputs, context_packet=node.context_packet)))
    site.analyze.assert_awaited_once_with(COMPETITOR)
    own_ids = {e.record.evidence_id for e in acquired.snapshot.evidence}
    external = [e for e in competitor.normalized_result.evidence if e.source_class is EvidenceSourceClass.EXTERNAL_PRIMARY]
    assert external and all(COMPETITOR in e.provenance and OWN not in e.provenance for e in external)
    assert own_ids.isdisjoint(e.evidence_id for e in external)
    local = json.loads(model.calls[0]["text"])["local_evidence"]
    assert all(PRODUCT not in e["value"] for e in local if e["source_class"] == "EXTERNAL_PRIMARY")


def test_no_hidden_owned_role_inference_or_owned_url_as_competitor():
    svc, graph = copilot(urls=(OWN,))
    req = request()
    output = asyncio.run(svc.execute(replace(req, message="Build strategy " + OWN)))
    assert output.kind is ResultKind.NEEDS_INPUT and "product" in output.clarification.alternatives[0]
    graph.start_compiled_run.assert_not_awaited()
    svc, graph = copilot(IntentKind.COMPARATIVE_POSITIONING, urls=(OWN,))
    acquired, _, _ = acquisition()
    req = attach_acquisition(replace(req, message="Compare " + OWN), acquired)
    output = asyncio.run(svc.execute(req))
    assert output.kind is ResultKind.NEEDS_INPUT
    assert "competitor_or_category_scope" in output.clarification.alternatives[0]
    graph.start_compiled_run.assert_not_awaited()


def test_inaccessible_page_has_typed_outcome_no_snapshot_and_no_durable_start():
    acquired, model, _ = acquisition(page={"ok": False})
    assert acquired.outcome is SourceOutcome.SOURCE_UNAVAILABLE and acquired.snapshot is None
    model.assert_not_awaited()
    svc, graph = copilot()
    output = asyncio.run(svc.execute(attach_acquisition(request(), acquired)))
    assert output.kind is ResultKind.NEEDS_INPUT
    assert "product" in output.clarification.alternatives[0]
    graph.start_compiled_run.assert_not_awaited()
    # Fetch failure does not discard explicit inputs already supplied by the caller.
    from app.marketing_orchestrator.strategy import REQUIRED_KEYS
    req = request(current_request=tuple(entry(k, "Confirmed " + k) for k in REQUIRED_KEYS))
    output = asyncio.run(svc.execute(attach_acquisition(req, acquired)))
    assert output.kind is ResultKind.WORKFLOW_STARTED


@pytest.mark.parametrize("statements", [
    [observation(SnapshotField.PRICING, "Price is 1 USD")],
    [dict(field=SnapshotField.PRODUCT.value, kind="OBSERVATION", text="Invented product", excerpts=[PRODUCT])],
    [observation(SnapshotField.PRODUCT, PRODUCT, evidence_id="evd_model_chosen")],
    [dict(field=SnapshotField.PRICING.value, kind="INFERENCE", text="Likely cheap", excerpts=[PRODUCT])],
    [dict(field="actual_profitability", kind="OBSERVATION", text=PRODUCT, excerpts=[PRODUCT])],
])
def test_hallucinated_or_incompatible_extraction_fails_closed(statements):
    result, _, _ = acquisition(raw=extraction(statements))
    assert result.outcome is SourceOutcome.INVALID_EXTRACTION and result.snapshot is None


def test_inference_and_unknown_are_kept_but_never_projected_or_confirmed():
    statements = [dict(field=SnapshotField.POSITIONING.value, kind="INFERENCE",
        text="Convenience may be part of positioning", excerpts=[PRODUCT]),
        dict(field=SnapshotField.PROOF.value, kind="UNKNOWN", text="Real satisfaction is unknown", excerpts=[])]
    result, _, _ = acquisition(raw=extraction(statements))
    assert result.outcome is SourceOutcome.ACQUIRED
    assert not project_snapshot(result.snapshot)
    assert result.snapshot.statements[0].kind is KnowledgeKind.INFERENCE
    assert "Real satisfaction is unknown" in result.snapshot.unknowns
    confirm = ConfirmedBusinessFact(snapshot_id=result.snapshot.snapshot_id,
        statement_ids=(result.snapshot.statements[0].statement_id,), confirmed_by="owner", confirmation_reference="123")
    with pytest.raises(ProductContextError):
        project_confirmation(result.snapshot, confirm)


def test_absent_pricing_is_unknown_not_inferred():
    result, _, _ = acquisition(raw=extraction([observation(SnapshotField.PRODUCT, PRODUCT)]))
    assert not any(s.field is SnapshotField.PRICING for s in result.snapshot.statements)
    assert any("stated_pricing" in u for u in result.snapshot.unknowns)


@pytest.mark.parametrize("key", ["product_truth", "existing_proof"])
def test_owned_layer_cannot_promote_site_claims_to_truth_or_proof(key):
    with pytest.raises(CopilotContractError):
        ContextResolver().resolve(owned_site_context=(entry(key, {"trust": "site_claim", "site_states": [LEADER]}),))
    alias = ContextEntry("owned_site_alias", replace(fact(key), input_key=None, value={"trust": "site_claim"}))
    with pytest.raises(CopilotContractError):
        ContextResolver().resolve(owned_site_context=(alias,))


@pytest.mark.parametrize("raw", ['{"statements": [], "statements": []}', 'not JSON', 'x' * 65537],
                         ids=["duplicate-key", "invalid-json", "oversized-json"])
def test_malformed_or_unbounded_extraction_has_no_partial_snapshot(raw):
    result, _, _ = acquisition(raw=raw)
    assert result.outcome is SourceOutcome.INVALID_EXTRACTION and result.snapshot is None


@pytest.mark.parametrize("analyzer_present,extractor_present", [(False, True), (True, False)])
def test_missing_capability_does_no_io(analyzer_present, extractor_present):
    site = SimpleNamespace(analyze_url=AsyncMock())
    model = AsyncMock()
    svc = OwnedProductEvidenceService(analyzer=site if analyzer_present else None,
        extractor=model if extractor_present else None)
    result = asyncio.run(svc.acquire(OwnedSiteRequest(owned_site_url=OWN)))
    assert result.outcome is SourceOutcome.CAPABILITY_UNAVAILABLE and result.snapshot is None
    site.analyze_url.assert_not_awaited()
    model.assert_not_awaited()


def extractor_failure_service(error):
    site = SimpleNamespace(analyze_url=AsyncMock(return_value=SimpleNamespace(url_summaries=[
        {"ok": True, "url": OWN, "main_text_excerpt": PRODUCT},
    ])))
    extractor = AsyncMock(side_effect=error)
    return OwnedProductEvidenceService(analyzer=site, extractor=extractor), extractor


def test_typed_extractor_failure_is_unavailable_without_raw_provider_details():
    svc, extractor = extractor_failure_service(ExtractorUnavailableError("RAW-PROVIDER-SECRET"))
    result = asyncio.run(svc.acquire(OwnedSiteRequest(owned_site_url=OWN)))
    extractor.assert_awaited_once()
    assert result.outcome is SourceOutcome.CAPABILITY_UNAVAILABLE
    assert result.snapshot is None
    for serialized in (result.model_dump_json(), str(result), repr(result)):
        assert "RAW-PROVIDER-SECRET" not in serialized
        assert "ExtractorUnavailableError" not in serialized


def test_extractor_programming_error_propagates_without_masking():
    defect = AssertionError("extractor programming defect")
    svc, extractor = extractor_failure_service(defect)
    with pytest.raises(AssertionError) as caught:
        asyncio.run(svc.acquire(OwnedSiteRequest(owned_site_url=OWN)))
    assert caught.value is defect
    extractor.assert_awaited_once()


def test_acquisition_only_connects_to_copilot_application_not_legacy_ingress():
    root = Path(__file__).resolve().parents[1]
    for directory in (root / "app", root / "bot"):
        consumers = [p for p in directory.rglob("*.py") if "product_context" not in p.parts
                     and "product_context" in p.read_text(encoding="utf-8")]
        allowed = {root / "app/marketing_copilot" / name for name in (
            "api_service.py", "production.py", "presentation.py", "provider_adapters.py")}
        assert set(consumers) <= allowed
    for path in (root / "app/product_context").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "app.module_execution" not in source
        assert "app.orchestration_runtime" not in source
        assert "app.llm" not in source


@pytest.mark.parametrize("host", ["2130706433", "127.1", "0x7f000001", "rebind.example"])
def test_owned_fetch_rejects_private_dns_answers_before_extraction(monkeypatch, host):
    async def exercise():
        loop = asyncio.get_running_loop()
        dns = AsyncMock(return_value=[(None, None, None, None, ("127.0.0.1", 443))])
        monkeypatch.setattr(loop, "getaddrinfo", dns)
        model = AsyncMock(side_effect=AssertionError("extractor must not run"))
        svc = OwnedProductEvidenceService(analyzer=build_owned_site_analyzer(), extractor=model)
        result = await svc.acquire(OwnedSiteRequest(owned_site_url="https://" + host + "/"))
        assert result.outcome is SourceOutcome.UNSAFE_SOURCE and result.snapshot is None
        model.assert_not_awaited()
    asyncio.run(exercise())


@pytest.mark.parametrize("url", ["http://localhost/", "http://127.0.0.1/", "http://10.2.3.4/",
    "http://172.16.0.1/", "http://192.168.0.1/", "http://169.254.169.254/", "http://[::1]/",
    "http://[fc00::1]/", "http://[fe80::1]/", "http://[::ffff:127.0.0.1]/",
    "https://user:secret@example.com/", "https://example.com:bad/", "https://[", "https://",
    "file:///etc/passwd", "https://example.com\\@127.0.0.1/", "https://example.com/\nheader",
    "https://[fe80::1%25eth0]/", "https://example.com:8443/"])
def test_unsafe_owned_url_rejected_before_analyzer_and_extractor(url):
    result, model, site = acquisition(url=url)
    assert result.outcome is SourceOutcome.UNSAFE_SOURCE
    model.assert_not_awaited()
    site.analyze_url.assert_not_awaited()


@pytest.mark.parametrize("case", ["private_redirect", "private_v6_redirect", "oversize", "stream_oversize", "empty", "timeout"])
def test_real_analyzer_safe_http_boundary_on_owned_path(monkeypatch, case):
    from app.services import safe_http, url_analyzer
    visited = []
    def handler(req):
        visited.append(str(req.url))
        if case.endswith("redirect"):
            target = "http://[fc00::1]/" if case == "private_v6_redirect" else "http://127.0.0.1/private"
            return httpx.Response(302, headers={"location": target})
        if case == "timeout":
            raise httpx.ReadTimeout("not exposed to caller")
        headers = {"content-type": "text/html"}
        if case == "oversize":
            headers["content-length"] = "1048577"
        return httpx.Response(200, headers=headers,
            stream=Stream([b"x" * 1048577] if case == "stream_oversize" else [b""]))
    async def fetch(url):
        return await safe_http.fetch_public(url, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(url_analyzer, "fetch_public", fetch)
    model = AsyncMock(side_effect=AssertionError("extractor must not run"))
    svc = OwnedProductEvidenceService(analyzer=build_owned_site_analyzer(), extractor=model)
    result = asyncio.run(svc.acquire(OwnedSiteRequest(owned_site_url=OWN)))
    assert result.outcome is (SourceOutcome.EMPTY_CONTENT if case == "empty" else
        SourceOutcome.SOURCE_UNAVAILABLE if case == "timeout" else SourceOutcome.UNSAFE_SOURCE)
    assert result.snapshot is None and visited == [OWN]
    model.assert_not_awaited()


def test_real_html_redirect_uses_final_url_and_only_literal_excerpts(monkeypatch):
    from app.services import safe_http, url_analyzer
    visited = []
    final = "https://owned.example/landing"
    def handler(req):
        visited.append(str(req.url))
        if str(req.url) == OWN:
            return httpx.Response(302, headers={"location": "/landing"})
        html = f"<html><head><title>Acme</title></head><body><p>{PRODUCT}</p><p>{AUDIENCE}</p><p>{JOB}</p><p>{PRICE}</p><p>{LEADER}</p></body></html>"
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, stream=Stream([html.encode()]))
    async def fetch(url):
        return await safe_http.fetch_public(url, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(url_analyzer, "fetch_public", fetch)
    svc = OwnedProductEvidenceService(analyzer=build_owned_site_analyzer(), extractor=AsyncMock(return_value=extraction()))
    result = asyncio.run(svc.acquire(OwnedSiteRequest(owned_site_url=OWN)))
    assert result.outcome is SourceOutcome.ACQUIRED
    assert visited == [OWN, final]
    assert result.snapshot.canonical_url == final
    assert all(e.page_url == final for e in result.snapshot.evidence)
