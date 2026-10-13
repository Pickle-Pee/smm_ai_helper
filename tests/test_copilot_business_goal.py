"""Business-goal adaptation consumes resolved assertions without semantic inference."""
import asyncio
import copy
import json
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.marketing_copilot import ContextResolver, ExecutionPolicy, IntentKind, OrchestratorAdapter
from app.marketing_copilot.application_contracts import CopilotRequest, ResultKind
from app.marketing_copilot.context_projection import merge_projected_context
from app.marketing_copilot.factory import build_marketing_copilot_service
from app.marketing_copilot.http_context import brand_entries, entry
from app.marketing_copilot.interpretation_store import validate_interpretation
from app.marketing_orchestrator import (
    MarketingOrchestratorPlanner, PlanningContext, PlanningInputKey, PlanningStatus,
    RequestInterpretation, Sensitivity, UpstreamFinding,
)
from app.module_registry import ModuleId
from app.orchestration_runtime.serialization import plan_from_json, plan_to_json
from tests.test_marketing_copilot import intent, projected
from tests.test_strategy_builder import strategy_compiled, strategy_executors

ABSENT = "Business goal was not supplied; no business objective is inferred."
GOAL = "Fill the two age groups by December"


def adapt(context, **options):
    semantic = intent(IntentKind.MARKETING_STRATEGY, **options)
    return OrchestratorAdapter().adapt(ExecutionPolicy().decide(semantic, context), context)


@pytest.mark.parametrize("intent_goal", [None, "Increase renewals"])
@pytest.mark.parametrize("layer", ["projection", "current_request", "project_run", "brand_profile", "conversation"])
def test_goal_from_resolved_layers_preserves_intent_precedence_and_provenance(layer, intent_goal):
    if layer == "projection":
        entries = merge_projected_context((), projected(business_goal=GOAL), GOAL)
        context = ContextResolver().resolve(current_request=entries)
    else:
        context = ContextResolver().resolve(**{layer: (entry("business_goal", GOAL, layer=layer),)})
    original = copy.copy(context)
    request, resolved = adapt(context, business_goal=intent_goal)
    assert request.business_goal == (intent_goal or GOAL)
    assert resolved == original
    assert context == original
    fact, = (*resolved.project_context, *resolved.known_facts)
    assert fact.value == GOAL
    assert fact.input_key is PlanningInputKey.BUSINESS_GOAL
    assert fact.authorized and fact.source == (*context.project_context, *context.known_facts)[0].source
    assert fact.evidence == () and fact.confidence == .7 and fact.sensitivity is Sensitivity.INTERNAL
    assert ABSENT not in resolved.assumptions


@pytest.mark.parametrize("explicit", [None, "Explicit renewals goal"])
def test_conflicting_layers_are_resolved_before_adaptation(explicit):
    current = () if explicit is None else (entry("business_goal", explicit),)
    merged = merge_projected_context(current, projected(business_goal=GOAL), GOAL)
    context = ContextResolver().resolve(current_request=merged,
        project_run=(entry("business_goal", "Run goal", layer="project"),),
        brand_profile=brand_entries({"goals": ["Brand goal"]}),
        conversation=(entry("business_goal", "Chat goal", layer="conversation"),))
    request, resolved = adapt(context)
    assert request.business_goal == (GOAL if explicit is None else explicit)
    assert not resolved.known_facts
    assert resolved.project_context == context.project_context
    assert len(resolved.project_context) == 1
    assert ABSENT not in resolved.assumptions


@pytest.mark.parametrize("value", [None, "", " ", [], {}])
def test_empty_current_goal_masks_projection_and_lower_goals(value):
    current = (entry("business_goal", value),)
    merged = merge_projected_context(current, projected(business_goal=GOAL), GOAL)
    assert merged == current
    context = ContextResolver().resolve(current_request=merged,
        brand_profile=brand_entries({"goals": ["Stale brand goal"]}))
    request, resolved = adapt(context)
    assert request.business_goal == "UNSPECIFIED"
    assert context.project_context == context.known_facts == ()
    assert resolved.assumptions == (ABSENT,)


@pytest.mark.parametrize("brand_goal", [None, "Authorized brand goal"])
def test_unauthorized_current_presence_masks_projection_but_does_not_win_resolution(brand_goal):
    unauthorized = entry("business_goal", "Unauthorized goal")
    current = (replace(unauthorized, fact=replace(unauthorized.fact, authorized=False)),)
    merged = merge_projected_context(current, projected(business_goal=GOAL), GOAL)
    assert merged == current
    context = ContextResolver().resolve(current_request=merged,
        brand_profile=brand_entries({"goals": [brand_goal]}) if brand_goal else ())
    request, resolved = adapt(context)
    assert request.business_goal == (brand_goal or "UNSPECIFIED")
    assert (ABSENT in resolved.assumptions) == (brand_goal is None)
    assert not resolved.project_context


@pytest.mark.parametrize("changes", [
    {"authorized": False}, {"sensitivity": Sensitivity.SECRET}, {"source": None},
    {"value": None}, {"value": " "}, {"value": 0}, {"value": False},
    {"value": [GOAL]}, {"value": {"claim": GOAL, "trust": "site_claim"}},
    {"input_key": None}, {"input_key": PlanningInputKey.PRODUCT},
])
def test_only_existing_typed_authorized_text_goals_are_adapted(changes):
    fact = replace(entry("business_goal", GOAL).fact, **changes)
    context = PlanningContext(project_context=(fact,))
    request, resolved = adapt(context)
    assert request.business_goal == "UNSPECIFIED"
    assert resolved.project_context == (fact,)
    assert resolved.assumptions == (ABSENT,)


def test_no_commercial_goal_is_inferred_from_other_text_or_upstream_findings():
    context = ContextResolver().resolve(current_request=(entry("message", GOAL), entry("product", "Course")),
        authorized_upstream_findings=(UpstreamFinding("positioning", "business_goal", GOAL),),
        assumptions=("Existing uncertainty",))
    request, resolved = adapt(context, decision_goal=GOAL)
    assert request.decision_goal == GOAL and request.business_goal == "UNSPECIFIED"
    assert set(resolved.assumptions) == {"Existing uncertainty", ABSENT}
    assert resolved.upstream_findings == context.upstream_findings


def historical_interpretation():
    # The persisted internal facts-array shape predates the fixed provider slots.
    # Its absent semantic goal remains absent after hydration and adaptation.
    return {"intent": {
        "kind": "MARKETING_STRATEGY", "requested_output": "Build a strategy",
        "decision_goal": "Choose actions", "business_goal": None, "subject": "Course",
        "external_evidence_required": False, "deterministic_calculation_required": False,
        "provided_urls": [], "source_references": [], "constraints": [],
        "confidence": .9, "ambiguous": False,
    }, "projection": {"facts": [{"key": "business_goal", "value": GOAL}]}}


def test_historical_persisted_interpretation_retains_shape_and_null_intent_goal():
    raw = historical_interpretation()
    original = copy.deepcopy(raw)
    interpreted = validate_interpretation(raw, GOAL)
    context = ContextResolver().resolve(current_request=merge_projected_context((), interpreted.projection, GOAL))
    request, resolved = OrchestratorAdapter().adapt(ExecutionPolicy().decide(interpreted.intent, context), context)
    assert request.business_goal == GOAL and ABSENT not in resolved.assumptions
    assert interpreted.intent.business_goal is None
    assert interpreted.model_dump(mode="json") == original == raw


@pytest.mark.parametrize("intent_goal", [None, "Intent goal"])
@pytest.mark.parametrize("explicit_goal", [None, "Explicit goal"])
def test_service_plans_deterministically_from_saved_interpretation_without_provider_calls(intent_goal, explicit_goal):
    raw = historical_interpretation()
    raw["intent"]["business_goal"] = intent_goal
    interpreted = validate_interpretation(raw, GOAL)
    provider = AsyncMock(side_effect=AssertionError("Provider must not be called"))
    executors = strategy_executors(provider)
    graph = SimpleNamespace(executors=executors, start_compiled_run=AsyncMock())
    service = build_marketing_copilot_service(intent_model=provider, registry_version="1.3.0",
        executor_registry=executors, graph_service=graph)
    facts = tuple(entry(k, v) for k, v in {
        "product": "Course", "target_or_target_hypothesis": "Students",
        "product_truth": "User asserted course contents", "tone": "Plain",
    }.items())
    if explicit_goal is not None:
        facts += (entry("business_goal", explicit_goal),)
    async def run():
        for entries in (facts, tuple(reversed(facts))):
            result = await service.execute(CopilotRequest(actor_id=1, request_id="goal", message=GOAL,
                current_request=entries), interpreted=interpreted)
            assert result.kind is ResultKind.WORKFLOW_STARTED
    asyncio.run(run())
    provider.assert_not_awaited()
    first, second = (call.kwargs["plan"] for call in graph.start_compiled_run.await_args_list)
    assert first == second
    assert [n.node_id for n in first.nodes] == ["positioning", "virtual_cmo", "experiments"]
    for node in first.nodes:
        assert ABSENT not in node.context_packet.assumptions
        goals = [f for f in (*node.context_packet.relevant_project_context, *node.context_packet.known_facts)
                 if f.input_key is PlanningInputKey.BUSINESS_GOAL]
        assert len(goals) == 1
        assert goals[0].value == (explicit_goal or GOAL)
        source = "request.projection" if explicit_goal is None else "request business input"
        assert source in goals[0].source
    assert plan_from_json(plan_to_json(first)) == first


def test_existing_unspecified_request_interpretation_and_compiled_plan_remain_valid():
    # Existing saved plans are restored directly, never re-adapted/replanned.
    request = RequestInterpretation(requested_output="strategy", decision_goal="Choose actions",
        business_goal="UNSPECIFIED", intent="MARKETING_STRATEGY", object="Course", depth="bounded",
        mode="PLANNING_ONLY", scenario_key="strategy_builder_v1")
    assert MarketingOrchestratorPlanner().plan(request, PlanningContext()).planning_status is PlanningStatus.BLOCKED
    existing = strategy_compiled()
    assert plan_from_json(plan_to_json(existing)) == existing
    raw = json.loads((Path(__file__).parent / "fixtures/compiled_execution_plan_v1.json").read_text())
    original = copy.deepcopy(raw)
    restored = plan_from_json(raw)
    assert restored.source_plan_id == "00f8ceca30d54c5197f3b29cb97f3413c5369cea6103b1c61cc3e4a38e999984"
    assert plan_to_json(restored) == original == raw


@pytest.mark.parametrize("kind,modules,scenarios,eligible", [
    (IntentKind.POST_GENERATION, (ModuleId.CREATOR,), (), True),
    (IntentKind.POST_GENERATION, (), ("explicit_single_module_v1",), True),
    (IntentKind.POST_GENERATION, (ModuleId.EXPERIMENTS,), (), False),
    (IntentKind.POST_GENERATION, (), ("strategy_builder_v1",), False),
    (IntentKind.MARKETING_STRATEGY, (ModuleId.VIRTUAL_CMO,), (), True),
    (IntentKind.MARKETING_STRATEGY, (), ("strategy_builder_v1",), True),
    (IntentKind.MARKETING_STRATEGY, (ModuleId.CREATOR,), (), False),
    (IntentKind.MARKETING_STRATEGY, (), (), False),
    (IntentKind.COMPARATIVE_POSITIONING, (), ("competitive_positioning_v1",), True),
    (IntentKind.COMPARATIVE_POSITIONING, (ModuleId.CREATOR,), (), False),
])
def test_context_goal_relevance_cannot_be_widened_by_adaptation(kind, modules, scenarios, eligible):
    fact = replace(entry("business_goal", GOAL).fact,
        module_relevance=frozenset(modules), scenario_relevance=frozenset(scenarios))
    context = PlanningContext(known_facts=(fact,))
    semantic = intent(kind)
    request, resolved = OrchestratorAdapter().adapt(ExecutionPolicy().decide(semantic, context), context)
    assert request.business_goal == (GOAL if eligible else "UNSPECIFIED")
    assert resolved.known_facts == (fact,)
    assert (ABSENT in resolved.assumptions) == (not eligible)
    if kind is IntentKind.MARKETING_STRATEGY:
        plan = MarketingOrchestratorPlanner().plan(request, resolved)
        cmo = next(n for n in plan.nodes if n.module_id is ModuleId.VIRTUAL_CMO)
        assert next(i.present for i in cmo.scoped_inputs if i.key == "business_goal") == eligible
        # Interpretation does not synthesize a fact or widen module-only scope.
        for node in plan.nodes:
            goals = [f for f in (*node.context_packet.known_facts, *node.context_packet.relevant_project_context)
                     if f.input_key is PlanningInputKey.BUSINESS_GOAL]
            assert all(f == fact for f in goals)
            if scenarios == () and modules == (ModuleId.VIRTUAL_CMO,) and node is not cmo:
                assert goals == []


def test_projected_goal_excerpt_is_carried_without_semantic_completion():
    excerpt = "выйти в плюс"
    context = ContextResolver().resolve(current_request=merge_projected_context(
        (), projected(business_goal=excerpt), "Нужно до декабря " + excerpt))
    request, resolved = adapt(context)
    assert request.business_goal == excerpt
    assert request.decision_goal == "Choose the message"
    assert resolved.project_context == context.project_context and ABSENT not in resolved.assumptions
