"""Real implementations through internal dispatcher, with no live provider calls."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.marketing_orchestrator import AuthorizedContextFact, ContextPacket, PlanningInputKey
from app.marketing_orchestrator.quality_gates.contracts import (
    BlockingReason, ClaimLineageType, Confidence, EvidenceSourceClass, ModuleResultStatus,
)
from app.module_execution import (
    ModuleCompatibilityError, ModuleExecutionContractError, ModuleExecutionRequest,
    ModuleExecutorDispatcher, ModuleExecutorRegistry, UpstreamExecutionResult,
)
from app.module_execution.executors import (
    CompetitorAnalysisExecutor, CreatorExecutor, ExecutorOutputError, PositioningExecutor,
    build_module_executor_registry, validate_executor_coherence,
)
from app.module_execution.executors.common import clamp_confidence
from app.module_execution.executors.positioning import POSITIONING_INPUTS
from app.module_registry import ModuleId, ModuleRegistry, ToolCapability

ROOT = Path(__file__).resolve().parents[1]
MODULES = (ModuleId.COMPETITOR_ANALYSIS, ModuleId.POSITIONING, ModuleId.CREATOR)
KEYS = ("competitor_analysis.v1", "positioning.v1", "creator.v1")


def fact(key, value=None, confidence=0.8, **kwargs):
    typed = next((k for k in PlanningInputKey if k.value == key), None)
    return AuthorizedContextFact("fact." + key, key, value if value is not None else key + " supplied value",
                                 input_key=typed, confidence=confidence,
                                 source="BRAND_PROFILE:owner snapshot", **kwargs)


def facts_for_module(module):
    if module is ModuleId.COMPETITOR_ANALYSIS:
        return (fact("competitor_url", "https://competitor.example/page"),)
    if module is ModuleId.POSITIONING:
        return tuple(fact(key) for key in POSITIONING_INPUTS)
    return (fact("product"), fact("target_or_target_hypothesis"), fact("message"), fact("asset_format", "text_post"))


def request(module, *, facts=None, outputs=None, upstream=(), tools=frozenset({ToolCapability.SITE_FETCH}), identity=None):
    return ModuleExecutionRequest(
        execution_id=identity or module.value.lower() + ".exec:1",
        module_id=module, objective="Prepare evidence-based marketing output",
        expected_outputs=outputs or ModuleRegistry.load().get(module).outputs,
        context_packet=ContextPacket(known_facts=facts_for_module(module) if facts is None else facts, available_tools=tools),
        upstream_results=upstream,
    )


def analyzer():
    return SimpleNamespace(analyze=AsyncMock(return_value=SimpleNamespace(url_summaries=[{
        "ok": True, "url": "https://competitor.example/page", "final_url": "https://competitor.example/page",
        "main_text_excerpt": "A public page advertises scheduling for local businesses.",
    }])))


class FakeModel:
    def __init__(self, mutate=None, use_parents=False):
        self.calls = []
        self.mutate = mutate
        self.use_parents = use_parents

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        data = json.loads(kwargs["text"])
        local = data["local_evidence"]
        ids = [e["evidence_id"] for e in local if e["source_class"] == "EXTERNAL_PRIMARY"]
        if not ids:
            ids = [e["evidence_id"] for e in local]
        parents = data["allowed_parent_claim_ids"] if self.use_parents else []
        result = {"outputs": [{"output_name": name, "text": "Bounded supported hypothesis: " + name,
                               "kind": "HYPOTHESIS", "confidence": "HIGH", "evidence_ids": ids,
                               "parent_claim_ids": parents} for name in data["expected_outputs"]],
                  "assumptions": [], "limitations": []}
        if "post" in kwargs["response_schema"]["properties"]:
            result["post"] = {"headline": "Plan your next post", "body": "Use the supplied product to prepare your content.", "cta": "Learn more"}
        if self.mutate:
            self.mutate(result, data)
        return json.dumps(result)


def dispatch(req, model=None, site=None):
    model = model if model is not None else FakeModel()
    registry = build_module_executor_registry(model_call=model, analyzer=site if site is not None else analyzer())
    binding = ModuleRegistry.load("1.1.0").get(req.module_id).execution_binding
    return asyncio.run(ModuleExecutorDispatcher(registry).dispatch(binding, req))


@pytest.mark.parametrize("module", MODULES)
def test_real_internal_dispatch_with_strict_schema_expert_core_and_requested_outputs(module, monkeypatch):
    from app.marketing_orchestrator.quality_gates import QualityGateEvaluator
    monkeypatch.setattr(QualityGateEvaluator, "evaluate", lambda *_: pytest.fail("Outer concern only"))
    model = FakeModel()
    result = dispatch(request(module), model)
    assert result.module_id is module
    assert result.schema_version == module.value.lower() + ".payload.v1"
    assert result.normalized_result.module_status is ModuleResultStatus.PASS_WITH_LIMITATIONS
    assert {c.declared_output_name for c in result.normalized_result.claims} == set(ModuleRegistry.load().get(module).outputs)
    assert len(model.calls) == 1
    call = model.calls[0]
    assert call["instruction"].count("<!-- EXPERT_CORE:") == 1
    assert "untrusted data" in call["instruction"]
    assert "chain-of-thought" in call["instruction"]
    schema = call["response_schema"]
    assert schema["additionalProperties"] is False
    for definition in schema["$defs"].values():
        if definition.get("type") == "object":
            assert definition["additionalProperties"] is False
            assert set(definition["required"]) == set(definition["properties"])


@pytest.mark.parametrize("module", MODULES)
def test_missing_inputs_and_missing_model_block_without_provider_call(module):
    model = FakeModel()
    site = analyzer()
    output = dispatch(request(module, facts=()), model, site)
    assert output.normalized_result.module_status is ModuleResultStatus.BLOCKED
    assert output.normalized_result.blocking_reasons
    assert not model.calls
    site.analyze.assert_not_awaited()
    registry = build_module_executor_registry(model_call=None, analyzer=site)
    result = asyncio.run(registry.resolve(module.value.lower() + ".v1").execute(request(module)))
    assert result.normalized_result.blocking_reasons == frozenset({BlockingReason.TOOL_UNAVAILABLE})
    site.analyze.assert_not_awaited()


@pytest.mark.parametrize("missing", POSITIONING_INPUTS)
def test_each_positioning_input_is_required_before_model_call(missing):
    model = FakeModel()
    result = dispatch(request(ModuleId.POSITIONING, facts=tuple(f for f in facts_for_module(ModuleId.POSITIONING) if f.label != missing)), model)
    assert result.normalized_result.module_status is ModuleResultStatus.BLOCKED
    assert missing in result.payload["missing_or_unsupported"]
    assert not model.calls


@pytest.mark.parametrize("key", ["product", "target_or_target_hypothesis", "message"])
def test_creator_missing_business_context_blocks(key):
    model = FakeModel()
    result = dispatch(request(ModuleId.CREATOR, facts=tuple(f for f in facts_for_module(ModuleId.CREATOR) if f.label != key)), model)
    assert result.normalized_result.module_status is ModuleResultStatus.BLOCKED
    assert not model.calls


@pytest.mark.parametrize("value", [None, "", "  ", {}, [], {"x": []}])
def test_empty_positioning_product_does_not_satisfy_structural_minimum(value):
    facts = list(facts_for_module(ModuleId.POSITIONING))
    facts[0] = replace(facts[0], value=value)
    model = FakeModel()
    assert dispatch(request(ModuleId.POSITIONING, facts=tuple(facts)), model).normalized_result.module_status is ModuleResultStatus.BLOCKED
    assert not model.calls


def test_unauthorized_facts_never_satisfy_input_or_enter_model_data():
    facts = tuple(replace(f, authorized=False) if f.label == "product" else f for f in facts_for_module(ModuleId.POSITIONING))
    model = FakeModel()
    assert dispatch(request(ModuleId.POSITIONING, facts=facts), model).normalized_result.module_status is ModuleResultStatus.BLOCKED
    assert not model.calls
    facts = (*facts_for_module(ModuleId.CREATOR), fact("secret", "private sentinel", authorized=False))
    dispatch(request(ModuleId.CREATOR, facts=facts), model)
    assert "private sentinel" not in model.calls[0]["text"]


@pytest.mark.parametrize("tools,missing_analyzer", [(frozenset(), False), (frozenset({ToolCapability.SITE_FETCH}), True)])
def test_competitor_missing_required_tool_blocks(tools, missing_analyzer):
    model, site = FakeModel(), analyzer()
    executor = CompetitorAnalysisExecutor(model_call=model, analyzer=None if missing_analyzer else site)
    result = asyncio.run(executor.execute(request(ModuleId.COMPETITOR_ANALYSIS, tools=tools)))
    assert result.normalized_result.blocking_reasons == frozenset({BlockingReason.TOOL_UNAVAILABLE})
    assert not model.calls
    site.analyze.assert_not_awaited()


@pytest.mark.parametrize("url", ["http://127.0.0.1", "http://localhost", "http://169.254.169.254", "file:///secret", "https://x.example:444"])
def test_unsafe_competitor_target_blocks_before_analyzer(url):
    model, site = FakeModel(), analyzer()
    output = dispatch(request(ModuleId.COMPETITOR_ANALYSIS, facts=(fact("competitor_url", url),)), model, site)
    assert output.normalized_result.module_status is ModuleResultStatus.BLOCKED
    site.analyze.assert_not_awaited()
    assert not model.calls


def test_competitor_name_without_search_and_empty_page_block():
    model, site = FakeModel(), analyzer()
    output = dispatch(request(ModuleId.COMPETITOR_ANALYSIS, facts=(fact("competitor_name", "A brand"),)), model, site)
    assert output.normalized_result.module_status is ModuleResultStatus.BLOCKED
    site.analyze.assert_not_awaited()
    site.analyze.return_value = SimpleNamespace(url_summaries=[{"ok": True, "url": "https://example.com"}])
    output = dispatch(request(ModuleId.COMPETITOR_ANALYSIS), model, site)
    assert output.normalized_result.module_status is ModuleResultStatus.BLOCKED
    assert not model.calls


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("failure", [RuntimeError("provider unavailable"), ValueError("provider refused"), asyncio.CancelledError()])
def test_model_provider_failure_propagates_identically_once(module, failure):
    model = AsyncMock(side_effect=failure)
    with pytest.raises(type(failure)) as caught:
        dispatch(request(module), model)
    assert caught.value is failure
    model.assert_awaited_once()


def test_analyzer_provider_failure_propagates_once():
    model, site = FakeModel(), analyzer()
    failure = RuntimeError("fetch failed")
    site.analyze.side_effect = failure
    with pytest.raises(RuntimeError) as caught:
        dispatch(request(ModuleId.COMPETITOR_ANALYSIS), model, site)
    assert caught.value is failure
    site.analyze.assert_awaited_once()
    assert not model.calls


@pytest.mark.parametrize("raw", [None, {}, "not json", "{}", '{"outputs":[],"outputs":[]}', '{"value":NaN}', "x" * 131073],
                         ids=["none", "dict", "non-json", "empty", "duplicate", "nan", "oversized"])
@pytest.mark.parametrize("module", MODULES)
def test_malformed_provider_output_fails_closed(module, raw):
    model = AsyncMock(return_value=raw)
    with pytest.raises(ExecutorOutputError):
        dispatch(request(module), model)
    model.assert_awaited_once()


@pytest.mark.parametrize("mutation", [
    lambda r, d: r.update(execution_id="model-generated"),
    lambda r, d: r.update(reasoning="hidden"),
    lambda r, d: r["outputs"][0].update(output_name="invented_output"),
    lambda r, d: r["outputs"][0].update(evidence_ids=["evd_unknown"]),
    lambda r, d: r["outputs"][0].update(parent_claim_ids=["clm_unknown"]),
    lambda r, d: r["outputs"][0].update(evidence_ids=[], parent_claim_ids=[]),
    lambda r, d: r["outputs"][0].update(text="x" * 4001),
    lambda r, d: r["outputs"][0].update(confidence=0.9),
    lambda r, d: r["outputs"].pop(),
])
@pytest.mark.parametrize("module", MODULES)
def test_output_contract_rejects_unknown_references_fields_and_missing_coverage(module, mutation):
    with pytest.raises(ExecutorOutputError):
        dispatch(request(module), FakeModel(mutation))


def test_first_party_and_public_page_provenance_remain_distinct():
    result = dispatch(request(ModuleId.COMPETITOR_ANALYSIS))
    evidence = result.normalized_result.evidence
    assert [e.source_class for e in evidence] == [EvidenceSourceClass.FIRST_PARTY, EvidenceSourceClass.EXTERNAL_PRIMARY]
    assert "BRAND_PROFILE:owner snapshot" in evidence[0].provenance
    assert "not independently verified" in evidence[0].provenance
    assert "https://competitor.example/page" in evidence[1].provenance
    position = dispatch(request(ModuleId.POSITIONING))
    assert all(e.source_class is EvidenceSourceClass.FIRST_PARTY for e in position.normalized_result.evidence)
    assert all(c.confidence is Confidence.MEDIUM for c in position.normalized_result.claims)


def test_positioning_uses_competitor_lineage_and_clamps_to_weakest_parent():
    competitor = dispatch(request(ModuleId.COMPETITOR_ANALYSIS), FakeModel(lambda r, d: r["outputs"][0].update(confidence="LOW")))
    upstream = (UpstreamExecutionResult(producer_node_id="competitor", result=competitor),)
    result = dispatch(request(ModuleId.POSITIONING, upstream=upstream), FakeModel(use_parents=True))
    parent_ids = {c.claim_id for c in competitor.normalized_result.claims}
    for claim in result.normalized_result.claims:
        assert claim.lineage_type is ClaimLineageType.DERIVES
        assert set(claim.parent_claim_ids) == parent_ids
        assert claim.confidence is Confidence.LOW
    assert not set(e.evidence_id for e in competitor.normalized_result.evidence) & set(e.evidence_id for e in result.normalized_result.evidence)
    assert all(item["confidence"] == "LOW" for item in result.payload["outputs"])


def test_creator_ready_post_and_positioning_only_audience_message_inputs():
    positioning = dispatch(request(ModuleId.POSITIONING))
    upstream = (UpstreamExecutionResult(producer_node_id="positioning", result=positioning),)
    result = dispatch(request(ModuleId.CREATOR, facts=(fact("product"), fact("asset_format", "text_post")), upstream=upstream), FakeModel(use_parents=True))
    assert set(result.payload["post"]) == {"headline", "body", "cta"}
    assert result.payload["post"]["body"]
    assert all(c.lineage_type is ClaimLineageType.DERIVES for c in result.normalized_result.claims)
    assert "image_id" not in json.dumps(dict(result.payload["post"]))


def test_creator_cannot_omit_lineage_when_upstream_supplies_required_context():
    positioning = dispatch(request(ModuleId.POSITIONING))
    upstream = (UpstreamExecutionResult(producer_node_id="positioning", result=positioning),)
    with pytest.raises(ExecutorOutputError):
        dispatch(request(ModuleId.CREATOR, facts=(fact("product"), fact("asset_format", "text_post")), upstream=upstream), FakeModel())


def test_outputs_can_be_a_declared_subset_and_unregistered_outputs_block():
    result = dispatch(request(ModuleId.POSITIONING, outputs=("category", "target")))
    assert {c.declared_output_name for c in result.normalized_result.claims} == {"category", "target"}
    model = FakeModel()
    result = dispatch(request(ModuleId.CREATOR, outputs=("image_reference",)), model)
    assert result.normalized_result.module_status is ModuleResultStatus.BLOCKED
    assert not model.calls


def test_executor_outputs_can_be_evaluated_by_outer_default_quality_gates():
    from app.marketing_orchestrator.quality_gates import EvaluationBatch, QualityGateEvaluator
    competitor = dispatch(request(ModuleId.COMPETITOR_ANALYSIS))
    positioning = dispatch(request(ModuleId.POSITIONING, upstream=(UpstreamExecutionResult(producer_node_id="competitor", result=competitor),)), FakeModel(use_parents=True))
    creator = dispatch(request(ModuleId.CREATOR, upstream=(UpstreamExecutionResult(producer_node_id="positioning", result=positioning),)), FakeModel(use_parents=True))
    batch = EvaluationBatch(batch_id="bat_internal", results=tuple(r.normalized_result for r in (competitor, positioning, creator)))
    evaluation = QualityGateEvaluator().evaluate(batch)
    assert len(evaluation.synthesis_manifest.accepted_result_ids) == 3


@pytest.mark.parametrize("format", ["image", "video", "carousel", "unknown"])
def test_creator_unsupported_asset_blocks_without_fake_media(format):
    facts = tuple(replace(f, value=format) if f.label == "asset_format" else f for f in facts_for_module(ModuleId.CREATOR))
    model = FakeModel()
    result = dispatch(request(ModuleId.CREATOR, facts=facts), model)
    assert result.normalized_result.blocking_reasons == frozenset({BlockingReason.MISSING_CAPABILITY})
    assert not model.calls


@pytest.mark.parametrize("confidence,expected", [(0.0, Confidence.UNKNOWN), (0.3, Confidence.LOW), (0.7, Confidence.MEDIUM), (1.0, Confidence.MEDIUM)])
def test_context_confidence_is_never_promoted(confidence, expected):
    facts = tuple(replace(f, confidence=confidence) for f in facts_for_module(ModuleId.POSITIONING))
    result = dispatch(request(ModuleId.POSITIONING, facts=facts))
    assert {c.confidence for c in result.normalized_result.claims} == {expected}
    assert clamp_confidence(Confidence.HIGH, [Confidence.MEDIUM, Confidence.UNKNOWN]) is Confidence.UNKNOWN


@pytest.mark.parametrize("name,kind", [("differentiation", "OBSERVATION"), ("points_of_difference", "INFERENCE"), ("USP_directions", "RECOMMENDATION")])
def test_positioning_cannot_present_differentiation_as_verified(name, kind):
    with pytest.raises(ExecutorOutputError):
        dispatch(request(ModuleId.POSITIONING, outputs=(name,)),
                 FakeModel(lambda r, d: r["outputs"][0].update(kind=kind)))


def test_positioning_rtb_cannot_be_supported_by_target_instead_of_product_truth():
    def wrong_support(result, data):
        target = next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"] == "target_or_target_hypothesis")
        result["outputs"][0]["evidence_ids"] = [target]
    with pytest.raises(ExecutorOutputError):
        dispatch(request(ModuleId.POSITIONING, outputs=("RTB",)), FakeModel(wrong_support))


def test_competitor_observation_cannot_use_first_party_evidence_only():
    def wrong_support(result, data):
        result["outputs"][0].update(kind="OBSERVATION", evidence_ids=[data["local_evidence"][0]["evidence_id"]])
    with pytest.raises(ExecutorOutputError):
        dispatch(request(ModuleId.COMPETITOR_ANALYSIS, outputs=("observable_positioning",)), FakeModel(wrong_support))


def test_creator_does_not_accept_failed_positioning_as_required_context():
    result = dispatch(request(ModuleId.POSITIONING, facts=()))
    model = FakeModel(use_parents=True)
    creator = dispatch(request(ModuleId.CREATOR, facts=(fact("product"), fact("asset_format", "text_post")),
                               upstream=(UpstreamExecutionResult(producer_node_id="positioning", result=result),)), model)
    assert creator.normalized_result.module_status is ModuleResultStatus.BLOCKED
    assert not model.calls


@pytest.mark.parametrize("module", MODULES)
def test_long_punctuated_execution_id_produces_safe_stable_qg_ids(module):
    req = request(module, identity="9" + ".:-a" * 31)
    first, second = dispatch(req), dispatch(req)
    assert first.normalized_result == second.normalized_result
    for record in (first.normalized_result, *first.normalized_result.claims, *first.normalized_result.evidence):
        identity = getattr(record, "result_id", None) or getattr(record, "claim_id", None) or record.evidence_id
        assert len(identity) <= 67 and "." not in identity and ":" not in identity


@pytest.mark.parametrize("executor", [PositioningExecutor(model_call=None), CreatorExecutor(model_call=None), CompetitorAnalysisExecutor(model_call=None, analyzer=None)])
def test_executor_direct_call_validates_request_type_and_module(executor):
    with pytest.raises(ModuleExecutionContractError):
        asyncio.run(executor.execute({}))
    with pytest.raises(ModuleCompatibilityError):
        asyncio.run(executor.execute(request(ModuleId.MENTOR, facts=(), outputs=("x",))))


def test_factory_inventory_coherence_and_no_constructor_provider_calls():
    model, site = AsyncMock(), analyzer()
    executors = build_module_executor_registry(model_call=model, analyzer=site)
    assert set(executors.executor_keys) == set(KEYS)
    metadata = ModuleRegistry.load("1.1.0")
    validate_executor_coherence(metadata, executors)
    model.assert_not_called()
    site.analyze.assert_not_called()
    with pytest.raises(ModuleCompatibilityError):
        validate_executor_coherence(ModuleRegistry.load(), executors)
    with pytest.raises(ModuleCompatibilityError):
        validate_executor_coherence(metadata, ModuleExecutorRegistry())
    objects = [executors.resolve(k) for k in KEYS]
    extra = SimpleNamespace(executor_key="extra.v1", module_id=ModuleId.MENTOR,
                            contract_version="module_executor.v1", execute=AsyncMock())
    with pytest.raises(ModuleCompatibilityError):
        validate_executor_coherence(metadata, ModuleExecutorRegistry([*objects, extra]))
    objects[0].module_id = ModuleId.CREATOR
    with pytest.raises(ModuleCompatibilityError):
        validate_executor_coherence(metadata, ModuleExecutorRegistry(objects))


def test_fresh_executor_import_does_not_load_runtime_owners_or_call_providers():
    script = '''
import sys, socket
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))
import app.module_execution.executors
forbidden = ('app.db', 'app.config', 'app.llm', 'app.agents', 'app.workflows', 'redis', 'aiogram', 'sqlalchemy')
assert not [m for m in sys.modules if any(m == p or m.startswith(p + '.') for p in forbidden)]
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_opt_in_public_analyzer_preserves_legacy_failure_behavior_and_never_uses_cache(monkeypatch):
    from app.module_execution.executors.capabilities import build_public_site_analyzer
    from app.services.url_analyzer import UrlAnalyzer
    failure = RuntimeError("transport failed")
    fetch = AsyncMock(side_effect=failure)
    monkeypatch.setattr("app.services.url_analyzer.fetch_public", fetch)
    legacy = asyncio.run(UrlAnalyzer().analyze("https://example.com"))
    assert legacy.url_summaries[0]["ok"] is False
    current = build_public_site_analyzer()
    assert current._analyzer._cache_sessions is None
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(current.analyze("https://example.com"))
    assert caught.value is failure
    assert fetch.await_count == 2


def test_public_analyzer_fetches_only_exact_url_and_preserves_observable_evidence(monkeypatch):
    import httpx
    from app.module_execution.executors.capabilities import build_public_site_analyzer
    url = "https://example.com/?handle=@anothercompetitor"
    fetch = AsyncMock(return_value=httpx.Response(200, headers={"content-type": "text/html"},
        text="<html><body><h1>Scheduling software for local businesses</h1></body></html>",
        request=httpx.Request("GET", url)))
    monkeypatch.setattr("app.services.url_analyzer.fetch_public", fetch)
    model = FakeModel(lambda r, d: r["outputs"][0].update(kind="OBSERVATION"))
    result = dispatch(request(ModuleId.COMPETITOR_ANALYSIS, facts=(fact("competitor_url", url),),
                              outputs=("observable_positioning",)), model, build_public_site_analyzer())
    fetch.assert_awaited_once_with(url)
    assert result.normalized_result.claims[0].claim_type.value == "OBSERVATION"
    assert result.normalized_result.evidence[-1].source_class is EvidenceSourceClass.EXTERNAL_PRIMARY
