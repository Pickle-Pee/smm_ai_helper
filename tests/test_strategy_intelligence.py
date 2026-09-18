"""Real dispatcher and Quality Gates, with deterministic fake provider responses."""
import asyncio
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.module_registry import ModuleId, ModuleRegistry, ModuleRegistryError, ModuleAvailabilityStatus
from app.module_execution import ModuleExecutorDispatcher, UpstreamExecutionResult
from app.module_execution.acceptance import fully_accepted
from app.module_execution.executors import build_module_executor_registry, ExecutorOutputError
from app.marketing_orchestrator.quality_gates import QualityGateEvaluator
from app.marketing_orchestrator.quality_gates.contracts import EvaluationBatch, Confidence, EvidenceSourceClass
from app.orchestration_runtime.serialization import result_from_json, result_to_json, plan_to_json, plan_from_json
from app.orchestration_runtime import PlanCompiler
from tests.test_module_executors import fact, request, FakeModel, analyzer, dispatch
from tests.graph_fakes import source_plan

MODULES = (ModuleId.MARKET_ANALYSIS, ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS)


def market_facts(source_class="EXTERNAL_PRIMARY"):
    return (fact("product_or_category", "Scheduling software"), fact("market_sources", [{
        "source_reference": "Supplied research document", "source_class": source_class,
        "excerpt": "Local businesses describe scheduling delays. Reported category revenue is 100 million dollars.",
    }]))


def cmo_facts():
    return (fact("business_goal", "Grow qualified demand"), fact("product", "Scheduling software"))


def positioning():
    return dispatch(request(ModuleId.POSITIONING, outputs=("differentiation",)))


def upstream(*results):
    return tuple(UpstreamExecutionResult(producer_node_id=r.module_id.value.lower(), result=r) for r in results)


class IntelligenceModel(FakeModel):
    async def __call__(self, **kwargs):
        raw = json.loads(await super().__call__(**kwargs))
        data = json.loads(kwargs["text"])
        # The inherited fake invokes mutate too early for structured additions.
        for statement in raw["outputs"]:
            statement["text"] = "Validate the supplied scheduling hypothesis"
            if "StrategyStatement" in kwargs["response_schema"].get("$defs", {}):
                statement["items"] = ["Prioritize validation of the supplied scheduling constraint"]
        if "experiments" in kwargs["response_schema"]["properties"]:
            raw["experiments"] = [{
                "hypothesis": "The supplied positioning resonates with the target",
                "target_metric": "Qualified inquiry rate", "intervention": "Compare positioning messages",
                "expected_signal": "Directional increase in qualified inquiries, to be tested",
                "failure_condition": "No directional improvement or worse lead quality",
                "minimum_required_inputs": ["Baseline and measurement definition"],
                "time_resource_constraints": [],
                "related_strategic_claim_ids": data["allowed_parent_claim_ids"][:8],
            }]
        if getattr(self, "change", None):
            self.change(raw, data)
        return json.dumps(raw)


def run(req, change=None, model=None, site=None):
    model = model or IntelligenceModel(use_parents=True)
    model.change = change
    executors = build_module_executor_registry(model_call=model, analyzer=analyzer(),
        registry_version="1.2.0", market_analyzer=site)
    return asyncio.run(ModuleExecutorDispatcher(executors).dispatch(
        ModuleRegistry.load("1.2.0").get(req.module_id).execution_binding, req))


def valid_request(module):
    if module is ModuleId.MARKET_ANALYSIS:
        return request(module, facts=market_facts())
    if module is ModuleId.VIRTUAL_CMO:
        return request(module, facts=cmo_facts(), upstream=upstream(positioning()))
    return request(module, facts=(), upstream=upstream(positioning()))


@pytest.mark.parametrize("module", MODULES)
def test_real_dispatch_schema_coverage_gates_serialization_and_no_invented_ids(module):
    req = valid_request(module)
    model = IntelligenceModel(use_parents=True)
    result = run(req, model=model)
    assert {c.declared_output_name for c in result.normalized_result.claims} == set(req.expected_outputs)
    assert result == result_from_json(result_to_json(result))
    manifest = QualityGateEvaluator().evaluate(EvaluationBatch(batch_id="bat_intelligence",
        results=tuple(u.result.normalized_result for u in req.upstream_results) + (result.normalized_result,))).synthesis_manifest
    assert fully_accepted(result, manifest.accepted_result_ids, manifest.accepted_claim_ids)
    excluded = result.normalized_result.claims[0].claim_id
    assert not fully_accepted(result, manifest.accepted_result_ids, tuple(c for c in manifest.accepted_claim_ids if c != excluded))
    assert len(model.calls) == 1 and "EXPERT_CORE" in model.calls[0]["instruction"]
    assert model.calls[0]["response_schema"]["additionalProperties"] is False
    assert all(c.claim_id.startswith("clm_") for c in result.normalized_result.claims)


@pytest.mark.parametrize("module,facts", [(ModuleId.MARKET_ANALYSIS, (fact("product_or_category"),)),
    (ModuleId.VIRTUAL_CMO, (fact("product"),)), (ModuleId.VIRTUAL_CMO, (fact("business_goal"),)),
    (ModuleId.EXPERIMENTS, ())])
def test_blocking_inputs_prevent_model_call(module, facts):
    model = IntelligenceModel()
    result = run(request(module, facts=facts), model=model)
    assert result.normalized_result.module_status.value == "BLOCKED"
    assert not model.calls
    assert {r.value for r in result.normalized_result.blocking_reasons} == {"MISSING_BLOCKING_INPUT"}


@pytest.mark.parametrize("source_class", ["EXTERNAL_PRIMARY", "EXTERNAL_SECONDARY"])
def test_supplied_source_class_preserved(source_class):
    result = run(request(ModuleId.MARKET_ANALYSIS, facts=market_facts(source_class)))
    assert result.normalized_result.evidence[-1].source_class.value == source_class


def test_first_party_only_limited_and_size_not_fabricated():
    req = request(ModuleId.MARKET_ANALYSIS, facts=(fact("product_or_category"), fact("existing_customers", "Customers report scheduling delays")))
    result = run(req)
    assert result.normalized_result.module_status.value == "PASS_WITH_LIMITATIONS"
    assert all(e.source_class is EvidenceSourceClass.FIRST_PARTY for e in result.normalized_result.evidence)
    for kind, text in [("OBSERVATION", "Customers report scheduling delays"), ("HYPOTHESIS", "Market size is 100 million")]:
        def mutate(raw, data):
            next(s for s in raw["outputs"] if s["output_name"] == "market_size_if_supported").update(kind=kind, text=text)
        with pytest.raises(ExecutorOutputError):
            run(req, mutate)


def test_source_url_requires_capability_and_fake_safe_fetch():
    req = request(ModuleId.MARKET_ANALYSIS, facts=(fact("product_or_category"),
        fact("market_source_urls", ["https://competitor.example/page"])))
    model = IntelligenceModel()
    assert run(req, model=model).normalized_result.module_status.value == "BLOCKED"
    assert not model.calls
    site = analyzer()
    result = run(req, site=site)
    site.analyze.assert_awaited_once_with("https://competitor.example/page")
    assert result.normalized_result.evidence[-1].source_class is EvidenceSourceClass.EXTERNAL_PRIMARY
    site.analyze.reset_mock()
    assert run(replace(req, context_packet=replace(req.context_packet, available_tools=frozenset())), site=site).normalized_result.module_status.value == "BLOCKED"
    site.analyze.assert_not_called()


@pytest.mark.parametrize("module", MODULES)
@pytest.mark.parametrize("failure", ["extra", "unknown_parent", "unsupported", "number", "duplicate"])
def test_hostile_outputs_fail_closed(module, failure):
    def mutate(raw, data):
        if failure == "extra": raw["technical_id"] = "invented"
        if failure == "unknown_parent": raw["outputs"][0]["parent_claim_ids"] = ["clm_invented"]
        if failure == "unsupported": raw["outputs"][0].update(parent_claim_ids=[], evidence_ids=[])
        if failure == "number": raw["outputs"][0]["text"] = "Conversion improves by 20%"
        if failure == "duplicate": raw["outputs"][-1] = raw["outputs"][0]
    with pytest.raises(ExecutorOutputError):
        run(valid_request(module), mutate)


@pytest.mark.parametrize("module", MODULES)
def test_provider_exception_propagates_once(module):
    error = RuntimeError("provider unavailable")
    model = AsyncMock(side_effect=error)
    with pytest.raises(RuntimeError) as caught:
        run(valid_request(module), model=model)
    assert caught.value is error
    model.assert_awaited_once()


@pytest.mark.parametrize("other", [(), (ModuleId.COMPETITOR_ANALYSIS,), (ModuleId.MARKET_ANALYSIS, ModuleId.COMPETITOR_ANALYSIS)])
def test_strategy_multisource_lineage_and_weakest_confidence(other):
    pos = positioning()
    pos = replace(pos, payload=result_to_json(pos)["payload"], normalized_result=replace(pos.normalized_result,
        claims=tuple(replace(c, confidence=Confidence.LOW) for c in pos.normalized_result.claims)))
    results = [pos]
    for module in other:
        results.append(run(valid_request(module)) if module is ModuleId.MARKET_ANALYSIS else dispatch(request(module)))
    result = run(request(ModuleId.VIRTUAL_CMO, facts=cmo_facts(), upstream=upstream(*results)))
    ids = {c.claim_id for r in results for c in r.normalized_result.claims}
    assert all(set(c.parent_claim_ids) == ids and c.confidence is Confidence.LOW for c in result.normalized_result.claims)
    assert all(e.source_class is EvidenceSourceClass.FIRST_PARTY for e in result.normalized_result.evidence)
    assert any("Economics absent" in l.description for l in result.normalized_result.limitations)
    assert all("items" in c.value for c in result.normalized_result.claims)


def test_one_constraint_and_at_most_three_priorities():
    for name, items in [("main_growth_constraint", ["One", "Two"]), ("strategic_priorities", ["A", "B", "C", "D"])]:
        with pytest.raises(ExecutorOutputError):
            run(valid_request(ModuleId.VIRTUAL_CMO), lambda raw, data: next(s for s in raw["outputs"] if s["output_name"] == name).update(items=items))


def test_experiments_from_cmo_and_structured_design_is_gated():
    cmo = run(request(ModuleId.VIRTUAL_CMO, facts=cmo_facts()))
    req = request(ModuleId.EXPERIMENTS, facts=(), upstream=upstream(cmo))
    result = run(req)
    assert "experiments" in result.normalized_result.claims[0].value
    assert result.payload["experiments"][0]["related_strategic_claim_ids"]
    assert result.payload["experiments"][0]["time_resource_constraints"] == ()


@pytest.mark.parametrize("field,value", [("expected_signal", "+20% conversion"), ("minimum_required_inputs", ["Sample of 1000"]),
    ("time_resource_constraints", ["Budget 500 dollars"]), ("related_strategic_claim_ids", ["clm_missing"])])
def test_experiment_no_fabricated_parameters_or_lineage(field, value):
    with pytest.raises(ExecutorOutputError):
        run(valid_request(ModuleId.EXPERIMENTS), lambda raw, data: raw["experiments"][0].update({field: value}))


def test_registry_version_matrix_and_metadata_unchanged():
    baseline = ModuleRegistry.load()
    assert baseline.version == "1.0.0"
    for version, count in [("1.1.0", 3), ("1.2.0", 6)]:
        metadata = ModuleRegistry.load(version)
        bindings = [d for d in metadata.descriptors if d.execution_binding]
        assert len(bindings) == count
        assert sum(d.availability_status is ModuleAvailabilityStatus.METADATA_ONLY for d in metadata.descriptors) == 15-count
        assert metadata.get(ModuleId.BUSINESS_DIAGNOSTICS).execution_binding is None
        for d in metadata.descriptors:
            assert replace(d, execution_binding=None, availability_status=ModuleAvailabilityStatus.METADATA_ONLY) == baseline.get(d.module_id)
        for d in bindings:
            assert d.execution_binding.executor_key == d.module_id.value.lower() + ".v1"
            assert d.execution_binding.contract_version == "module_executor.v1"
            assert d.execution_binding.compatibility == "exact"
    assert {d.module_id for d in ModuleRegistry.load("1.2.0").descriptors if d.execution_binding} == {
        ModuleId.COMPETITOR_ANALYSIS, ModuleId.POSITIONING, ModuleId.CREATOR, *MODULES}


def test_v12_checksum_and_fail_closed_binding_set():
    raw = json.loads(Path("app/module_registry/v1.2.0.json").read_text(encoding="utf-8"))
    normalized = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(normalized).hexdigest() == "8b54ade6748a3ff04d098035efc991625b042652bf6abc517beae67c46551d38"
    for module in MODULES:
        corrupt = copy.deepcopy(raw)
        row = next(d for d in corrupt["modules"] if d["module_id"] == module.value)
        row.update(execution_binding=None, availability_status="metadata_only")
        with pytest.raises(ModuleRegistryError): ModuleRegistry.from_mapping(corrupt)
    corrupt = copy.deepcopy(raw)
    row = next(d for d in corrupt["modules"] if d["module_id"] == "BUSINESS_DIAGNOSTICS")
    row.update(availability_status="execution_bound", execution_binding=copy.deepcopy(raw["modules"][0]["execution_binding"]))
    with pytest.raises(ModuleRegistryError): ModuleRegistry.from_mapping(corrupt)


@pytest.mark.parametrize("version", ["1.1.0", "1.2.0"])
def test_runtime_exact_version_survives_recreation(version):
    executors = build_module_executor_registry(model_call=FakeModel(), analyzer=analyzer(), registry_version="1.2.0")
    plan = PlanCompiler(ModuleRegistry.load(version), executors).compile(source_plan())
    restored = plan_from_json(json.loads(json.dumps(plan_to_json(plan))))
    assert restored.registry_version == version
    assert restored == plan
    assert plan_from_json(plan_to_json(restored)).registry_version == version
    future = plan_to_json(plan)
    future["registry_version"] = "1.3.0"
    with pytest.raises(ValueError): plan_from_json(future)


def test_market_exact_numeric_source_observation_and_safe_adapter(monkeypatch):
    import httpx
    from app.module_execution.executors.capabilities import build_public_site_analyzer
    sentence = "Reported category revenue is 100 million dollars."
    def observation(raw, data):
        raw["outputs"][0].update(text=sentence, kind="OBSERVATION")
    req = request(ModuleId.MARKET_ANALYSIS, facts=market_facts(), outputs=("market_size_if_supported",))
    assert run(req, observation).normalized_result.claims[0].value == sentence
    url = "https://source.example/research"
    fetch = AsyncMock(return_value=httpx.Response(200, headers={"content-type": "text/html"},
        text="<html><body><p>Local businesses report recurring scheduling delays.</p></body></html>", request=httpx.Request("GET", url)))
    monkeypatch.setattr("app.services.url_analyzer.fetch_public", fetch)
    run(request(ModuleId.MARKET_ANALYSIS, facts=(fact("product_or_category"),
        fact("market_source_urls", [url]))), site=build_public_site_analyzer())
    fetch.assert_awaited_once_with(url)


def test_market_source_failure_propagates_once_and_empty_page_blocks():
    req = request(ModuleId.MARKET_ANALYSIS, facts=(fact("product_or_category"),
        fact("market_source_urls", ["https://source.example/research"])))
    site = analyzer()
    failure = TimeoutError("source unavailable")
    site.analyze.side_effect = failure
    model = IntelligenceModel()
    with pytest.raises(TimeoutError) as caught: run(req, model=model, site=site)
    assert caught.value is failure and site.analyze.await_count == 1 and not model.calls
    site.analyze.side_effect = None
    site.analyze.return_value.url_summaries = [{"ok": False}]
    assert run(req, model=model, site=site).normalized_result.module_status.value == "BLOCKED"
    assert not model.calls


def test_market_unknown_source_class_and_unapproved_facts_do_not_call_model():
    facts = market_facts("MODEL_KNOWLEDGE")
    model = IntelligenceModel()
    assert run(request(ModuleId.MARKET_ANALYSIS, facts=facts), model=model).normalized_result.module_status.value == "BLOCKED"
    assert not model.calls
    facts = (facts[0], replace(facts[1], value=[dict(facts[1].value[0])], authorized=False))
    assert run(request(ModuleId.MARKET_ANALYSIS, facts=facts), model=model).normalized_result.module_status.value == "BLOCKED"
    assert not model.calls


def test_cmo_without_upstream_can_use_first_party_but_cannot_invent_parent():
    req = request(ModuleId.VIRTUAL_CMO, facts=cmo_facts())
    result = run(req)
    assert all(c.evidence_ids and not c.parent_claim_ids for c in result.normalized_result.claims)
    with pytest.raises(ExecutorOutputError):
        run(req, lambda raw, data: raw["outputs"][0].update(parent_claim_ids=["clm_hypothetical"]))


def test_experiment_preserves_supplied_constraints_and_accepts_explicit_numeric_hypothesis():
    pos = positioning()
    pos = replace(pos, payload=result_to_json(pos)["payload"], normalized_result=replace(pos.normalized_result,
        claims=(replace(pos.normalized_result.claims[0], value="Test a 20% conversion uplift hypothesis"),)))
    req = request(ModuleId.EXPERIMENTS, facts=(fact("budget", "Budget 500 dollars"),), upstream=upstream(pos))
    def supplied(raw, data):
        raw["experiments"][0].update(time_resource_constraints=["Budget 500 dollars"],
            expected_signal="Test a 20% conversion uplift hypothesis")
    result = run(req, supplied)
    assert result.payload["experiments"][0]["time_resource_constraints"] == ("Budget 500 dollars",)
    assert result.normalized_result.claims[0].evidence_ids
    with pytest.raises(ExecutorOutputError): run(req)


def test_non_hypothesis_upstream_does_not_enable_experiments():
    pos = positioning()
    from app.marketing_orchestrator.quality_gates.contracts import ClaimType
    pos = replace(pos, payload=result_to_json(pos)["payload"], normalized_result=replace(pos.normalized_result,
        claims=tuple(replace(c, claim_type=ClaimType.RECOMMENDATION) for c in pos.normalized_result.claims)))
    model = IntelligenceModel()
    assert run(request(ModuleId.EXPERIMENTS, facts=(), upstream=upstream(pos)), model=model).normalized_result.module_status.value == "BLOCKED"
    assert not model.calls


def test_new_factory_has_no_constructor_calls_and_does_not_change_default():
    model, site = AsyncMock(), analyzer()
    old = build_module_executor_registry(model_call=model, analyzer=site)
    new = build_module_executor_registry(model_call=model, analyzer=site, market_analyzer=site, registry_version="1.2.0")
    assert len(old.executor_keys) == 3 and len(new.executor_keys) == 6
    model.assert_not_called()
    site.analyze.assert_not_called()


def test_runtime_does_not_relax_descriptor_compatibility_for_v12():
    metadata = ModuleRegistry.load("1.2.0")
    metadata = ModuleRegistry(version="1.2.0", descriptors=tuple(replace(d, purpose="changed")
        if d.module_id is ModuleId.POSITIONING else d for d in metadata.descriptors))
    executors = build_module_executor_registry(model_call=FakeModel(), analyzer=analyzer(), registry_version="1.2.0")
    with pytest.raises(ValueError): PlanCompiler(metadata, executors).compile(source_plan())
