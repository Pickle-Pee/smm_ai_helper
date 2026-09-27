"""Copilot foundation contract tests; all model responses are explicit doubles."""
import asyncio
from dataclasses import FrozenInstanceError
from itertools import product
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.marketing_copilot import (
    ContextEntry, ContextResolver, CopilotContractError, ExecutionDecision,
    ExecutionMode, ExecutionPolicy, IntentKind, MarketingIntent, MarketingIntentInterpreter,
    OrchestratorAdapter, ReasonCode,
)
from app.marketing_orchestrator import (
    AuthorizedContextFact, ExecutionReadiness, MarketingOrchestratorPlanner, PlanningContext,
    PlanningInputKey, PlanningStatus, RequestInterpretation, Sensitivity, UpstreamFinding,
)
from app.module_registry import ModuleAvailabilityStatus, ModuleId, ModuleRegistry, ToolCapability
from app.marketing_copilot.context_projection import (
    BusinessFactCandidate, NaturalLanguageContextProjection, InterpretedRequest, merge_projected_context,
)


def intent(kind=IntentKind.POST_GENERATION, **overrides):
    values = dict(
        kind=kind, requested_output="A useful marketing result", decision_goal="Choose the message",
        subject="Photography course", external_evidence_required=False,
        deterministic_calculation_required=False, provided_urls=(), source_references=(),
        constraints=(), confidence=0.9, ambiguous=False,
    )
    values.update(overrides)
    return MarketingIntent(**values)


def entry(key="product", *, value="Our product", fact_id="fact.product", source="profile:7",
          authorized=True, modules=(ModuleId.POSITIONING,), scenarios=(), confidence=0.8,
          sensitivity=Sensitivity.INTERNAL, input_key=PlanningInputKey.PRODUCT):
    return ContextEntry(key, AuthorizedContextFact(
        fact_id=fact_id, label="A semantic fact", value=value, source=source, input_key=input_key,
        module_relevance=frozenset(modules), scenario_relevance=frozenset(scenarios),
        evidence=("source:7",), confidence=confidence, sensitivity=sensitivity, authorized=authorized,
    ))


def positioning_context():
    facts = tuple(entry(key.value, fact_id=f"fact.{key.value.replace('_', '-')}", input_key=key) for key in (
        PlanningInputKey.PRODUCT, PlanningInputKey.TARGET_OR_TARGET_HYPOTHESIS,
        PlanningInputKey.CUSTOMER_JOB_OR_NEED, PlanningInputKey.RELEVANT_ALTERNATIVE,
        PlanningInputKey.PRODUCT_TRUTH,
    ))
    return ContextResolver().resolve(brand_profile=facts)


def projected(**values):
    return NaturalLanguageContextProjection(facts=tuple(
        BusinessFactCandidate(key=k, value=v) for k, v in values.items()))


@pytest.mark.parametrize("key", ["business_goal", "product", "target_or_target_hypothesis",
    "customer_job_or_need", "relevant_alternative", "product_truth", "existing_proof",
    "geography", "economics", "message", "tone"])
def test_projection_allowlist_has_server_owned_provenance(key):
    context = ContextResolver().resolve(current_request=merge_projected_context((), projected(**{key: "user fact"}), "user fact"))
    fact = context.project_context[0]
    assert fact.label == key and fact.value == "user fact"
    assert fact.source == "CURRENT_REQUEST:Authenticated request.projection business input; not independently verified"
    assert fact.evidence == () and fact.confidence == .7
    assert fact.authorized and fact.sensitivity is Sensitivity.INTERNAL
    assert fact.input_key == next((k for k in PlanningInputKey if k.value == key), None)


@pytest.mark.parametrize("key", ["module_id", "executor_key", "registry_version", "execution_binding",
    "tool_key", "scenario_key", "job_kind", "source_role", "source_class", "ToolCapability",
    "authorized", "sensitivity", "module_relevance", "scenario_relevance", "owned_site_url",
    "competitor_urls", "competitor_or_category_scope", "market_source_urls", "market_sources", "target"])
def test_projection_rejects_authority_fields_and_noncanonical_keys(key):
    with pytest.raises(ValidationError):
        BusinessFactCandidate(key=key, value="injected")
    with pytest.raises(ValidationError):
        BusinessFactCandidate(key="product", value="user fact", **{key: "injected"})


@pytest.mark.parametrize("value", ["", " ", pytest.param("x" * 4001, id="oversized-value"),
    1, True, {"source_class": "EXTERNAL_PRIMARY"}, ["nested"]])
def test_projection_values_are_bounded_strict_text(value):
    with pytest.raises(ValidationError):
        projected(product=value)


def test_projection_rejects_duplicate_keys_and_unbounded_lists():
    candidate = BusinessFactCandidate(key="product", value="x" * 4000)
    assert len(candidate.value) == 4000
    for facts in ((candidate, candidate), (candidate,) * 12):
        with pytest.raises(ValidationError):
            NaturalLanguageContextProjection(facts=facts)


@pytest.mark.parametrize("raw", [
    pytest.param(InterpretedRequest(intent=intent(), projection=projected()).model_dump_json().replace(
        '"facts":[]', '"facts":[],"facts":[]'), id="duplicate-projection-property"),
    pytest.param(InterpretedRequest(intent=intent(), projection=projected(product="post")).model_dump_json().replace(
        '"value":"post"', '"value":"post","value":"post"'), id="duplicate-candidate-property"),
    'null', '[]', '{}', pytest.param('x' * 98305, id="oversized-response"),
])
def test_combined_interpretation_rejects_malformed_responses(raw):
    model = AsyncMock(return_value=raw)
    with pytest.raises(CopilotContractError):
        asyncio.run(MarketingIntentInterpreter(model).interpret_request("post"))
    model.assert_awaited_once()


def test_combined_interpretation_validates_literal_excerpts_in_one_call():
    response = InterpretedRequest(intent=intent(), projection=projected(product="Курс фотографии"))
    model = AsyncMock(return_value=response.model_dump_json())
    interpreter = MarketingIntentInterpreter(model)
    assert asyncio.run(interpreter.interpret_request("Курс фотографии для начинающих")) == response
    model.assert_awaited_once()
    assert set(model.call_args.kwargs["response_schema"]["properties"]) == {"intent", "projection"}
    with pytest.raises(CopilotContractError, match="literal"):
        asyncio.run(interpreter.interpret_request("Придумай продукт"))


@pytest.mark.parametrize("value", ["Product A", "", " ", None])
def test_projection_merge_preserves_explicit_masks_and_all_lower_layers(value):
    from app.marketing_copilot.http_context import entry as http_entry
    explicit = (http_entry("product", value),)
    merged = merge_projected_context(explicit, projected(product="Product B"), "Мы продаём Product B")
    assert merged == explicit
    resolved = ContextResolver().resolve(current_request=merged,
        project_run=(http_entry("product", "PROJECT", layer="project"),),
        brand_profile=(http_entry("product", "BRAND", layer="brand"),),
        conversation=(http_entry("product", "CHAT", layer="chat"),))
    assert [f.value for f in resolved.project_context] == ([value] if value == "Product A" else [])
    assert not resolved.known_facts


def test_projection_outranks_fallbacks_without_weakening_duplicate_protection():
    from app.marketing_copilot.http_context import entry as http_entry
    merged = merge_projected_context((), projected(product="CURRENT"), "CURRENT")
    resolved = ContextResolver().resolve(current_request=merged,
        brand_profile=(http_entry("product", "BRAND", layer="brand"),),
        conversation=(http_entry("product", "CHAT", layer="chat"),))
    assert [f.value for f in resolved.project_context] == ["CURRENT"] and not resolved.known_facts
    duplicates = merge_projected_context((http_entry("product", "A"), http_entry("product", "B")),
                                        projected(product="CURRENT"), "CURRENT")
    with pytest.raises(CopilotContractError, match="Duplicate"):
        ContextResolver().resolve(current_request=duplicates)


@pytest.mark.parametrize("mode,bits", tuple(product(ExecutionMode, product((False, True), repeat=3))))
def test_execution_selector_invariant_is_immediate(mode, bits):
    selectors = dict(
        tool_key="lead_funnel_calculator_v1" if bits[0] else None,
        module_id=ModuleId.CREATOR if bits[1] else None,
        scenario_key="strategy_builder_v1" if bits[2] else None,
    )
    valid = ((mode is ExecutionMode.CONVERSATION and sum(bits) == 0)
             or (sum(bits) == 1 and bits[list(ExecutionMode).index(mode) - 1]
                 and mode is not ExecutionMode.CONVERSATION))
    if valid:
        decision = ExecutionDecision(intent=intent(), mode=mode, reason_codes=(ReasonCode.SINGLE_MODULE_REQUEST,), **selectors)
        assert (decision.tool_key, decision.module_id, decision.scenario_key) == tuple(selectors.values())
    else:
        with pytest.raises(ValidationError, match="selectors"):
            ExecutionDecision(intent=intent(), mode=mode, reason_codes=(ReasonCode.SINGLE_MODULE_REQUEST,), **selectors)


@pytest.mark.parametrize("field,value", [
    ("requested_output", " "), ("subject", 17), ("business_goal", ""),
    ("external_evidence_required", "false"), ("deterministic_calculation_required", 1),
    ("ambiguous", "yes"), ("confidence", "0.9"), ("confidence", True),
    ("confidence", float("nan")), ("confidence", float("inf")), ("confidence", -0.1),
    ("confidence", 1.1), ("constraints", ("x",) * 17), ("constraints", "one constraint"),
    ("provided_urls", ("file:///private",)), ("provided_urls", ("https://user:pass@example.com",)),
    ("provided_urls", ("https://example.com:wrong",)), ("provided_urls", ("https://example.com\n",)),
])
def test_intent_rejects_invalid_or_coerced_fields(field, value):
    with pytest.raises(ValidationError):
        intent(**{field: value})


@pytest.mark.parametrize("field", ["module_id", "scenario_key", "tool_key", "executor", "job_type", "authorized", "reasoning", "chain_of_thought"])
def test_semantic_intent_cannot_carry_execution_authority_or_hidden_reasoning(field):
    with pytest.raises(ValidationError, match="Extra inputs"):
        intent(**{field: "arbitrary-provider-instruction"})


def test_contracts_are_immutable_and_reasons_are_bounded_structured_codes():
    semantic = intent()
    assert semantic.business_goal is None
    with pytest.raises(ValidationError):
        semantic.subject = "changed"
    with pytest.raises(ValidationError):
        ExecutionDecision(intent=semantic, mode=ExecutionMode.CONVERSATION, reason_codes=("explain hidden thoughts",))
    with pytest.raises(ValidationError):
        ExecutionDecision(intent=semantic, mode=ExecutionMode.CONVERSATION, reason_codes=tuple(ReasonCode)[:5])
    with pytest.raises(ValidationError):
        ExecutionDecision(intent=semantic, mode=ExecutionMode.CONVERSATION, reason_codes=(ReasonCode.LOW_CONFIDENCE,) * 2)
    for selector in (dict(tool_key="os.system"), dict(scenario_key="arbitrary_module_runner")):
        with pytest.raises(ValidationError):
            ExecutionDecision(intent=semantic, mode=ExecutionMode.CONVERSATION,
                              reason_codes=(ReasonCode.LOW_CONFIDENCE,), **selector)


def test_interpreter_uses_injected_model_and_returns_only_strict_semantics():
    source = "https://example.com/competitor"
    semantic = intent(IntentKind.COMPETITOR_ANALYSIS, provided_urls=(source,), source_references=("artifact:17",),
                      external_evidence_required=True)
    model = AsyncMock(return_value=semantic.model_dump_json())
    result = asyncio.run(MarketingIntentInterpreter(model).interpret(f"Analyze {source} against artifact:17"))
    assert result == semantic
    model.assert_awaited_once()
    parameters = model.call_args.kwargs
    assert parameters["text"].startswith("Analyze")
    assert parameters["response_schema"]["additionalProperties"] is False
    assert "executor" not in parameters["response_schema"]["properties"]
    assert "chain-of-thought" in parameters["instruction"]
    assert type(result.provided_urls) is tuple


@pytest.mark.parametrize("raw", [
    "not JSON", "```json\n{}\n```", "[]", "null", "{}", '{"kind":"POST_GENERATION","kind":"UNSUPPORTED"}',
    intent().model_dump_json().replace('"confidence":0.9', '"confidence":NaN'),
    intent().model_dump_json().replace('"POST_GENERATION"', '"RUN_PYTHON_EXECUTOR"'),
    json.dumps({**intent().model_dump(mode="json"), "reasoning": "private model reasoning"}),
    json.dumps({**intent().model_dump(mode="json"), "confidence": "0.9"}),
    {}, pytest.param(" " * 32769, id="oversized-response"),
])
def test_interpreter_rejects_malformed_model_output_without_repair_or_retry(raw):
    model = AsyncMock(return_value=raw)
    with pytest.raises(CopilotContractError) as caught:
        asyncio.run(MarketingIntentInterpreter(model).interpret("Write a post"))
    assert "private model reasoning" not in str(caught.value)
    model.assert_awaited_once()


def test_interpreter_does_not_invent_references_or_retry_provider_failure():
    model = AsyncMock(return_value=intent(provided_urls=("https://invented.example",)).model_dump_json())
    with pytest.raises(CopilotContractError, match="references"):
        asyncio.run(MarketingIntentInterpreter(model).interpret("Write a post"))
    broken = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    with pytest.raises(RuntimeError, match="unavailable"):
        asyncio.run(MarketingIntentInterpreter(broken).interpret("Write a post"))
    broken.assert_awaited_once()


@pytest.mark.parametrize("request_text", ["", " ", pytest.param("a" * 12001, id="oversized-request"), b"not text"])
def test_interpreter_validates_request_before_model_call(request_text):
    model = AsyncMock()
    with pytest.raises(CopilotContractError):
        asyncio.run(MarketingIntentInterpreter(model).interpret(request_text))
    model.assert_not_called()


@pytest.mark.parametrize("kind,options,mode,selector", [
    (IntentKind.LEAD_FUNNEL_CALCULATION, {"deterministic_calculation_required": True}, ExecutionMode.DIRECT_TOOL, "lead_funnel_calculator_v1"),
    (IntentKind.POST_GENERATION, {}, ExecutionMode.SINGLE_MODULE, ModuleId.CREATOR),
    (IntentKind.TEXT_EDITING, {}, ExecutionMode.SINGLE_MODULE, ModuleId.COPY_EDITOR),
    (IntentKind.COMPETITOR_ANALYSIS, {"external_evidence_required": True}, ExecutionMode.SINGLE_MODULE, ModuleId.COMPETITOR_ANALYSIS),
    (IntentKind.POSITIONING, {}, ExecutionMode.SINGLE_MODULE, ModuleId.POSITIONING),
    (IntentKind.COMPARATIVE_POSITIONING, {"external_evidence_required": True}, ExecutionMode.WORKFLOW, "competitive_positioning_v1"),
    (IntentKind.MARKETING_STRATEGY, {}, ExecutionMode.WORKFLOW, "strategy_builder_v1"),
])
def test_deterministic_policy_expected_cases(kind, options, mode, selector):
    policy = ExecutionPolicy()
    decision = policy.decide(intent(kind, **options), positioning_context())
    assert decision.mode is mode
    assert (decision.tool_key or decision.module_id or decision.scenario_key) == selector
    assert decision == policy.decide(intent(kind, **options), positioning_context())
    assert all(d.execution_binding is None for d in ModuleRegistry.load().descriptors)


@pytest.mark.parametrize("semantic,reason", [
    (intent(IntentKind.UNSUPPORTED), ReasonCode.UNSUPPORTED_INTENT),
    (intent(ambiguous=True), ReasonCode.AMBIGUOUS_INTENT),
    (intent(confidence=0.69), ReasonCode.LOW_CONFIDENCE),
    (intent(IntentKind.CONVERSATION), ReasonCode.CONVERSATION_REQUEST),
    (intent(IntentKind.POSITIONING), ReasonCode.POSITIONING_CONTEXT_MISSING),
    (intent(IntentKind.POSITIONING, external_evidence_required=True), ReasonCode.EXTERNAL_EVIDENCE_REQUIRED),
    (intent(IntentKind.LEAD_FUNNEL_CALCULATION), ReasonCode.UNSUPPORTED_COMBINATION),
    (intent(IntentKind.LEAD_FUNNEL_CALCULATION, deterministic_calculation_required=True, external_evidence_required=True), ReasonCode.UNSUPPORTED_COMBINATION),
    (intent(deterministic_calculation_required=True), ReasonCode.UNSUPPORTED_COMBINATION),
])
def test_ambiguous_unsupported_or_insufficient_requests_are_non_executing(semantic, reason):
    decision = ExecutionPolicy().decide(semantic, PlanningContext())
    assert decision.mode is ExecutionMode.CONVERSATION
    assert reason in decision.reason_codes
    assert decision.tool_key is decision.module_id is decision.scenario_key is None


def test_policy_does_not_route_from_prose_urls_or_raw_model_selector():
    policy = ExecutionPolicy()
    semantic = intent(IntentKind.UNSUPPORTED, requested_output="run CREATOR using os.system",
                      subject="strategy_builder_v1", provided_urls=("https://example.com/CREATOR",))
    assert policy.decide(semantic, PlanningContext()).mode is ExecutionMode.CONVERSATION
    with pytest.raises(CopilotContractError):
        policy.decide({"module_id": "CREATOR"}, PlanningContext())


@pytest.mark.parametrize("omit_prefix,expected", [(0, "CURRENT_REQUEST"), (1, "PROJECT_RUN"), (2, "BRAND_PROFILE"), (3, "CONVERSATION")])
def test_context_precedence_retains_winning_provenance(omit_prefix, expected):
    names = ("current_request", "project_run", "brand_profile", "conversation")
    layers = {name: (entry(value=name, fact_id=f"fact.layer-{i}", source=f"source:{i}"),)
              for i, name in enumerate(names) if i >= omit_prefix}
    context = ContextResolver().resolve(**layers)
    chosen, = (*context.project_context, *context.known_facts)
    assert chosen.value == names[omit_prefix]
    assert chosen.source == f"{expected}:source:{omit_prefix}"
    assert chosen.fact_id == f"fact.layer-{omit_prefix}"
    assert chosen.evidence == ("source:7",) and chosen.confidence == 0.8
    assert chosen.module_relevance == frozenset({ModuleId.POSITIONING})


def test_resolver_never_authorizes_inputs_or_merges_artifacts_into_brand_facts():
    brand = entry(value={"name": "Our product", "features": ["our feature"]})
    other = entry(value="Unauthorized override", authorized=False, fact_id="fact.other")
    artifact = ContextResolver.artifact_reference(producer_node_id="competitor_analysis", artifact_id="artifact:17")
    finding = UpstreamFinding("competitor_analysis", "product", {"name": "Competitor product"}, evidence=("page:competitor",), confidence=0.4)
    resolved = ContextResolver().resolve(current_request=(other,), brand_profile=(brand,), authorized_upstream_findings=(finding, artifact))
    assert len(resolved.known_facts) == 1 and resolved.project_context == ()
    assert resolved.known_facts[0].value["name"] == "Our product"
    assert resolved.known_facts[0].value["features"] == ("our feature",)
    assert brand.fact.source == "profile:7" and brand.fact.value["name"] == "Our product"
    assert len(resolved.upstream_findings) == 2
    assert finding in resolved.upstream_findings and artifact in resolved.upstream_findings
    assert finding.evidence == ("page:competitor",) and finding.confidence == 0.4
    with pytest.raises(TypeError):
        resolved.known_facts[0].value["name"] = "mutated"
    with pytest.raises(FrozenInstanceError):
        brand.semantic_key = "different"


@pytest.mark.parametrize("empty", [None, " ", {}, [], {"unknown": None}])
def test_explicit_unknown_masks_stale_brand_value_and_cannot_satisfy_planner(empty):
    context = ContextResolver().resolve(current_request=(entry(value=empty),), brand_profile=(entry(value="stale"),))
    assert context.project_context == context.known_facts == ()
    assert ExecutionPolicy().decide(intent(IntentKind.POSITIONING), context).mode is ExecutionMode.CONVERSATION


@pytest.mark.parametrize("value", [0, False])
def test_zero_false_are_not_missing_context(value):
    result = ContextResolver().resolve(current_request=(entry(value=value),))
    assert result.project_context[0].value == value


def test_resolver_rejects_ambiguous_semantics_missing_provenance_and_untyped_artifacts():
    with pytest.raises(CopilotContractError, match="semantic_key"):
        ContextEntry("not_the_product", entry().fact)
    with pytest.raises(CopilotContractError, match="source"):
        ContextEntry("product", AuthorizedContextFact("fact.no-source", "product", "known"))
    with pytest.raises(CopilotContractError, match="Duplicate semantic_key"):
        ContextResolver().resolve(brand_profile=(entry(), entry(fact_id="fact.other")))
    with pytest.raises(CopilotContractError, match="typed entries"):
        ContextResolver().resolve(brand_profile={"product": "not tagged"})
    with pytest.raises(CopilotContractError, match="UpstreamFinding"):
        ContextResolver().resolve(authorized_upstream_findings=({"product": "other"},))


def test_unscoped_or_unauthorized_facts_do_not_make_positioning_context_sufficient():
    for authorized, modules in ((False, (ModuleId.POSITIONING,)), (True, (ModuleId.CREATOR,))):
        facts = tuple(entry(f.input_key.value, input_key=f.input_key, fact_id=f.fact_id,
                            authorized=authorized, modules=modules).fact for f in positioning_context().known_facts)
        decision = ExecutionPolicy().decide(intent(IntentKind.POSITIONING), PlanningContext(known_facts=facts))
        assert decision.mode is ExecutionMode.CONVERSATION


@pytest.mark.parametrize("missing", [PlanningInputKey.PRODUCT, PlanningInputKey.TARGET_OR_TARGET_HYPOTHESIS,
    PlanningInputKey.CUSTOMER_JOB_OR_NEED, PlanningInputKey.RELEVANT_ALTERNATIVE, PlanningInputKey.PRODUCT_TRUTH])
def test_each_positioning_requirement_is_needed_and_upstream_cannot_replace_it(missing):
    known = tuple(f for f in positioning_context().known_facts if f.input_key is not missing)
    finding = UpstreamFinding("competitor_analysis", "upstream.product", {missing.value: "Competitor assumption"})
    decision = ExecutionPolicy().decide(intent(IntentKind.POSITIONING), PlanningContext(known_facts=known, upstream_findings=(finding,)))
    assert decision.mode is ExecutionMode.CONVERSATION
    assert ReasonCode.POSITIONING_CONTEXT_MISSING in decision.reason_codes


def test_model_copy_validation_bypass_does_not_cross_policy_or_adapter_boundary():
    unsafe_intent = intent().model_copy(update={"kind": "UNREVIEWED_MODULE"})
    with pytest.raises(ValidationError):
        ExecutionPolicy().decide(unsafe_intent, PlanningContext())
    decision = ExecutionPolicy().decide(intent(), PlanningContext())
    unsafe_decision = decision.model_copy(update={"tool_key": "lead_funnel_calculator_v1"})
    with pytest.raises(ValidationError, match="selectors"):
        OrchestratorAdapter().adapt(unsafe_decision, PlanningContext())


def test_context_resolution_is_order_independent_and_preserves_sensitivity():
    first = entry(sensitivity=Sensitivity.SECRET)
    second = entry("geographic_scope", input_key=PlanningInputKey.GEOGRAPHIC_SCOPE, fact_id="fact.geography")
    resolver = ContextResolver()
    a = resolver.resolve(brand_profile=(first, second))
    b = resolver.resolve(brand_profile=(second, first))
    assert a == b
    assert next(f for f in a.known_facts if f.fact_id == first.fact.fact_id).sensitivity is Sensitivity.SECRET


def test_adapter_preserves_existing_selector_contract_and_does_not_infer_business_goal():
    context = ContextResolver().resolve(brand_profile=(entry(),), constraints=("Preserve brand voice",),
                                        available_tools=frozenset({ToolCapability.SITE_FETCH}))
    semantic = intent(constraints=("No invented claims",), provided_urls=("https://example.com",), source_references=("artifact:unverified",))
    request, resolved = OrchestratorAdapter().adapt(ExecutionPolicy().decide(semantic, context), context)
    assert type(request) is RequestInterpretation and type(resolved) is PlanningContext
    assert request.requested_module == "CREATOR" and request.scenario_key is None
    assert request.mode == "PLANNING_ONLY" and request.business_goal == "UNSPECIFIED"
    assert "No invented claims" in request.constraints and "Preserve brand voice" in request.constraints
    assert any("not supplied" in a for a in resolved.assumptions)
    assert resolved.known_facts == context.known_facts and resolved.upstream_findings == ()
    assert resolved.available_tools == context.available_tools
    assert context.assumptions == ()  # Caller state not mutated.
    assert all("artifact:unverified" not in str(f.value) for f in resolved.known_facts)


@pytest.mark.parametrize("kind,options", [(IntentKind.CONVERSATION, {}), (IntentKind.LEAD_FUNNEL_CALCULATION, {"deterministic_calculation_required": True})])
def test_adapter_refuses_modes_that_cannot_meet_existing_orchestrator_selector(kind, options):
    decision = ExecutionPolicy().decide(intent(kind, **options), PlanningContext())
    with pytest.raises(CopilotContractError, match="selector"):
        OrchestratorAdapter().adapt(decision, PlanningContext())


def test_strategy_adapter_is_planning_only_and_groups_missing_first_party_context():
    context = PlanningContext()
    decision = ExecutionPolicy().decide(intent(IntentKind.MARKETING_STRATEGY, business_goal="Qualified demand"), context)
    request, resolved = OrchestratorAdapter().adapt(decision, context)
    assert request.scenario_key == "strategy_builder_v1" and request.requested_module is None
    assert request.business_goal == "Qualified demand"
    plan = MarketingOrchestratorPlanner().plan(request, resolved)
    assert plan.planning_status is PlanningStatus.BLOCKED
    assert {q.input_key.value for q in plan.blocking_questions} == {
        "product", "target_or_target_hypothesis", "customer_job_or_need", "relevant_alternative", "product_truth"
    }
    assert plan.execution_readiness is ExecutionReadiness.PLANNING_ONLY


def test_comparative_adapter_preserves_upstream_scope_and_existing_planning_only_graph():
    scenario = "competitive_positioning_v1"
    facts = tuple(entry(key.value, input_key=key, fact_id=f"fact.{key.value.replace('_', '-')}",
                        modules=(), scenarios=(scenario,)) for key in PlanningInputKey)
    finding = UpstreamFinding("competitor_analysis", "comparison", "Observed alternatives", evidence=("source:one",), confidence=0.5)
    context = ContextResolver().resolve(project_run=facts, authorized_upstream_findings=(finding,))
    decision = ExecutionPolicy().decide(intent(IntentKind.COMPARATIVE_POSITIONING, external_evidence_required=True), context)
    request, resolved = OrchestratorAdapter().adapt(decision, context)
    assert request.requested_module is None and request.scenario_key == scenario
    plan = MarketingOrchestratorPlanner().plan(request, resolved)
    assert [n.module_id for n in plan.nodes] == [ModuleId.COMPETITOR_ANALYSIS, ModuleId.POSITIONING]
    assert plan.execution_readiness is ExecutionReadiness.PLANNING_ONLY
    assert plan.nodes[0].context_packet.upstream_findings == ()
    assert plan.nodes[1].context_packet.upstream_findings == (finding,)


def test_foundation_uses_no_runtime_execution_or_implicit_provider(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Non-executable foundation called a runtime boundary")
    monkeypatch.setattr("app.llm.openai_text.chat", forbidden)
    monkeypatch.setattr("app.services.agent_runner.AgentRunner.run", forbidden)
    monkeypatch.setattr("app.services.qc_service.QCService.find_issues", forbidden)
    monkeypatch.setattr("app.services.url_analyzer.UrlAnalyzer.analyze", forbidden)
    registry = ModuleRegistry.load()
    decision = ExecutionPolicy(registry).decide(intent(), PlanningContext())
    request, context = OrchestratorAdapter().adapt(decision, PlanningContext())
    assert MarketingOrchestratorPlanner(registry).plan(request, context).execution_readiness is ExecutionReadiness.PLANNING_ONLY
    assert all(d.availability_status is ModuleAvailabilityStatus.METADATA_ONLY and d.execution_binding is None for d in registry.descriptors)
    root = Path(__file__).resolve().parents[1]
    consumers = [p for directory in (root / "app", root / "bot") for p in directory.rglob("*.py")
                 if "marketing_copilot" not in p.parts and "marketing_copilot" in p.read_text(encoding="utf-8")]
    assert set(consumers) == {root / "app/product_context/projection.py", root / "app/routers/copilot.py"}
    # Only the explicit projection and separate Copilot router consume this boundary.
