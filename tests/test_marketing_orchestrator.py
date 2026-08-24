from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import MappingProxyType

import pytest

from app.marketing_orchestrator import (
    AuthorizedContextFact,
    BlockingQuestion,
    DataSufficiency,
    ExecutionReadiness,
    GraphDependency,
    InvalidInterpretationError,
    InvalidPlanError,
    MarketingOrchestratorPlanner,
    PlanningContext,
    PlanningStatus,
    PlanningStopCondition,
    RequestInterpretation,
    Sensitivity,
    StructuralValidity,
    UnknownModulePlanningError,
    UpstreamFinding,
)
from app.marketing_orchestrator.validation import PlanValidator
from app.module_registry import ModuleAvailabilityStatus, ModuleId, ModuleRegistry
from app.services.agent_registry import AgentRegistry


SCENARIO = "new_positioning_v1"
REQUIRED_POSITIONING_KEYS = (
    "product_or_category",
    "geographic_scope",
    "competitor_or_category_scope",
    "observable_evidence",
    "product",
    "target_or_target_hypothesis",
    "customer_job_or_need",
    "relevant_alternative",
    "product_truth",
)
EXPECTED_NODE_IDS = ("market_analysis", "competitor_analysis", "positioning")
EXPECTED_MODULES = (
    ModuleId.MARKET_ANALYSIS,
    ModuleId.COMPETITOR_ANALYSIS,
    ModuleId.POSITIONING,
)
EXPECTED_EDGES = (
    ("competitor_analysis", "positioning"),
    ("market_analysis", "positioning"),
)


def interpretation(*, module=None, scenario=SCENARIO):
    return RequestInterpretation(
        requested_output="Positioning recommendation",
        decision_goal="Choose a defensible position",
        business_goal="Improve qualified demand",
        intent="PLAN",
        object="POSITIONING",
        depth="WORKING",
        mode="EXECUTION",
        constraints=("Do not invent evidence",),
        requested_module=module,
        scenario_key=None if module is not None else scenario,
    )


def fact(key, *, modules=(), scenarios=(SCENARIO,), value="known", authorized=True, sensitivity=Sensitivity.INTERNAL):
    return AuthorizedContextFact(
        key=key,
        value=value,
        module_relevance=frozenset(modules),
        scenario_relevance=frozenset(scenarios),
        source="caller",
        evidence=(f"evidence:{key}",),
        confidence="HIGH",
        sensitivity=sensitivity,
        authorized=authorized,
    )


def complete_context(**overrides):
    data = {
        "known_facts": tuple(fact(key) for key in REQUIRED_POSITIONING_KEYS),
        "assumptions": ("Target is provisional",),
        "constraints": ("Use authorized context only",),
    }
    data.update(overrides)
    return PlanningContext(**data)


@pytest.fixture
def registry():
    return ModuleRegistry.load()


@pytest.fixture
def planner(registry):
    return MarketingOrchestratorPlanner(registry)


@pytest.fixture
def valid_plan(planner):
    return planner.plan(interpretation(), complete_context())


def test_interpretation_requires_exactly_one_structured_selector():
    with pytest.raises(ValueError, match="exactly one"):
        RequestInterpretation("o", "d", "b", "i", "x", "w", "m")
    with pytest.raises(ValueError, match="exactly one"):
        RequestInterpretation("o", "d", "b", "i", "x", "w", "m", requested_module="CREATOR", scenario_key=SCENARIO)


def test_planner_rejects_untyped_free_text(planner):
    with pytest.raises(InvalidInterpretationError, match="RequestInterpretation"):
        planner.plan("make positioning")  # type: ignore[arg-type]


def test_contracts_are_deeply_immutable(planner):
    source = {"nested": ["one"]}
    context_fact = fact("product", value=source)
    source["nested"].append("two")
    context = complete_context(known_facts=(context_fact, *complete_context().known_facts[1:]))
    plan = planner.plan(interpretation(), context)

    assert isinstance(context_fact.value, MappingProxyType)
    assert context_fact.value["nested"] == ("one",)
    assert isinstance(plan.nodes, tuple)
    assert isinstance(plan.nodes[0].context_packet.known_facts, tuple)
    with pytest.raises(FrozenInstanceError):
        plan.planning_status = PlanningStatus.INVALID  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        plan.nodes.append(plan.nodes[0])  # type: ignore[attr-defined]


def test_identical_inputs_produce_identical_plan_without_randomness(planner):
    first = planner.plan(interpretation(), complete_context())
    second = planner.plan(interpretation(), complete_context())

    assert first == second
    assert first.plan_id == second.plan_id
    assert len(first.plan_id) == 64
    assert tuple(node.node_id for node in first.nodes) == EXPECTED_NODE_IDS


def test_single_module_canonical_id_produces_exactly_one_planning_only_node(planner, registry):
    plan = planner.plan(interpretation(module="CREATOR"), PlanningContext())

    assert plan.scenario_key == "explicit_single_module_v1"
    assert len(plan.nodes) == 1
    assert plan.nodes[0].module_id is ModuleId.CREATOR
    assert plan.dependencies == ()
    assert plan.execution_readiness is ExecutionReadiness.PLANNING_ONLY
    assert plan.nodes[0].expected_outputs == registry.get(ModuleId.CREATOR).outputs
    assert plan.nodes[0].quality_gate == registry.get(ModuleId.CREATOR).quality_gate
    assert {node.module_id for node in plan.nodes} == {ModuleId.CREATOR}


def test_single_module_alias_resolves_to_canonical_id_only(planner):
    plan = planner.plan(interpretation(module="usp and-offer"), PlanningContext())

    assert plan.nodes[0].module_id is ModuleId.POSITIONING
    assert all("usp and-offer" not in str(item).casefold() for item in plan.nodes)


@pytest.mark.parametrize("module", ["unknown", "not-an-approved-alias"])
def test_unknown_module_or_alias_is_rejected(planner, module):
    with pytest.raises(UnknownModulePlanningError, match="unknown module"):
        planner.plan(interpretation(module=module), PlanningContext())


def test_new_positioning_has_exact_independent_graph(valid_plan):
    assert tuple(node.node_id for node in valid_plan.nodes) == EXPECTED_NODE_IDS
    assert tuple(node.module_id for node in valid_plan.nodes) == EXPECTED_MODULES
    assert tuple((edge.upstream_node_id, edge.downstream_node_id) for edge in valid_plan.dependencies) == EXPECTED_EDGES
    assert valid_plan.nodes[0].parallelizable is True
    assert valid_plan.nodes[1].parallelizable is True
    assert valid_plan.nodes[0].parallel_group == valid_plan.nodes[1].parallel_group == "evidence_analysis"
    assert valid_plan.nodes[2].parallelizable is False
    assert valid_plan.nodes[2].dependency_references == ("competitor_analysis", "market_analysis")
    assert len(valid_plan.nodes) == 3


def test_valid_plan_separates_status_sufficiency_and_readiness(valid_plan):
    assert valid_plan.structural_validity is StructuralValidity.VALID
    assert valid_plan.planning_status is PlanningStatus.VALIDATED
    assert valid_plan.data_sufficiency is DataSufficiency.PARTIAL  # preferred inputs remain limitations
    assert valid_plan.execution_readiness is ExecutionReadiness.PLANNING_ONLY
    assert valid_plan.stop_condition is PlanningStopCondition.PLAN_COMPLETE


def test_unsupported_scenario_returns_explicit_result_without_graph(planner):
    plan = planner.plan(interpretation(scenario="full_strategy_v1"), PlanningContext())

    assert plan.planning_status is PlanningStatus.UNSUPPORTED
    assert plan.stop_condition is PlanningStopCondition.UNSUPPORTED_SCENARIO
    assert plan.nodes == ()
    assert plan.dependencies == ()


def test_context_scoping_includes_module_and_scenario_facts_and_excludes_unrelated(planner):
    scenario_fact = fact("product", scenarios=(SCENARIO,))
    market_fact = fact("market_only", modules=(ModuleId.MARKET_ANALYSIS,), scenarios=())
    unrelated = fact("unrelated", modules=(ModuleId.CREATOR,), scenarios=())
    unauthorized = fact("secret", scenarios=(SCENARIO,), authorized=False, sensitivity=Sensitivity.SECRET)
    context = complete_context(known_facts=(scenario_fact, market_fact, unrelated, unauthorized, *complete_context().known_facts[1:]))

    plan = planner.plan(interpretation(), context)
    market_keys = {item.key for item in plan.nodes[0].context_packet.known_facts}
    competitor_keys = {item.key for item in plan.nodes[1].context_packet.known_facts}

    assert "product" in market_keys and "product" in competitor_keys
    assert "market_only" in market_keys and "market_only" not in competitor_keys
    assert "unrelated" not in market_keys | competitor_keys
    assert "secret" not in market_keys | competitor_keys


def test_upstream_findings_only_enter_declared_dependent_packet(planner):
    context = complete_context(
        upstream_findings=(
            UpstreamFinding("market_analysis", "segments", ("A",)),
            UpstreamFinding("competitor_analysis", "gaps", ("B",)),
            UpstreamFinding("unknown", "ignore", "C"),
        )
    )
    plan = planner.plan(interpretation(), context)

    assert plan.nodes[0].context_packet.upstream_findings == ()
    assert plan.nodes[1].context_packet.upstream_findings == ()
    assert tuple(item.producer_node_id for item in plan.nodes[2].context_packet.upstream_findings) == (
        "market_analysis", "competitor_analysis"
    )


def test_known_inputs_are_not_asked_and_missing_inputs_are_bounded(planner):
    empty = planner.plan(interpretation(), PlanningContext())
    partial = planner.plan(
        interpretation(),
        PlanningContext(known_facts=(fact("product_or_category"), fact("geographic_scope"))),
    )

    assert empty.planning_status is PlanningStatus.BLOCKED
    assert len(empty.blocking_questions) == 3
    assert len({item.input_key for item in empty.blocking_questions}) == 3
    assert tuple(item.input_key for item in empty.blocking_questions) == (
        "product_or_category", "geographic_scope", "competitor_or_category_scope"
    )
    assert all(item.input_key not in {"product_or_category", "geographic_scope"} for item in partial.blocking_questions)


def test_missing_preferred_input_is_limitation_not_question(planner):
    plan = planner.plan(interpretation(), complete_context())

    assert any("preferred input" in item for item in plan.limitations)
    assert all("business_model" != item.input_key for item in plan.blocking_questions)
    assert plan.stop_condition is PlanningStopCondition.PLAN_COMPLETE


def test_registry_bindings_and_existing_agent_registry_remain_unchanged(registry, valid_plan):
    assert registry.version == "1.0.0"
    assert all(item.availability_status is ModuleAvailabilityStatus.METADATA_ONLY for item in registry.descriptors)
    assert all(item.execution_binding is None for item in registry.descriptors)
    assert valid_plan.execution_readiness is ExecutionReadiness.PLANNING_ONLY
    assert AgentRegistry.supported_agent_types() == {"strategy", "content", "analytics", "promo", "trends"}


def test_planning_does_not_load_product_prompt_or_use_external_boundaries(monkeypatch, registry):
    planner = MarketingOrchestratorPlanner(registry)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("planning must not read runtime prompts or call external boundaries")

    monkeypatch.setattr(Path, "read_text", forbidden)
    plan = planner.plan(interpretation(), complete_context())

    assert plan.planning_status is PlanningStatus.VALIDATED
    source = Path("app/marketing_orchestrator/planner.py").read_bytes().decode("utf-8")
    forbidden_imports = ("openai", "QCService", "AgentRunner", "TaskRouter", "TaskPipelineService", "MarketingWorkflowPersistenceService", "redis", "sqlalchemy")
    assert all(name not in source for name in forbidden_imports)
    assert "orchestrator-production.md" not in source


def test_public_dtos_are_unchanged():
    from app.schemas import BrandProfileRead, TaskStartRequest

    assert set(TaskStartRequest.model_fields) == {"user", "agent_type", "task_description", "answers", "mode"}
    assert "brand_name" in BrandProfileRead.model_fields
    assert not any("orchestration" in name.casefold() for name in TaskStartRequest.model_fields)


def test_validator_rejects_duplicate_node_id(valid_plan, registry):
    duplicate = replace(valid_plan.nodes[1], node_id=valid_plan.nodes[0].node_id)
    malformed = replace(valid_plan, nodes=(valid_plan.nodes[0], duplicate, valid_plan.nodes[2]))
    with pytest.raises(InvalidPlanError, match="duplicate node"):
        PlanValidator(registry).validate(malformed)


def test_validator_rejects_unknown_or_unresolved_module(valid_plan, registry):
    malformed_node = replace(valid_plan.nodes[0], module_id="MARKET ANALYSIS")  # type: ignore[arg-type]
    malformed = replace(valid_plan, nodes=(malformed_node, *valid_plan.nodes[1:]))
    with pytest.raises(InvalidPlanError, match="unresolved alias"):
        PlanValidator(registry).validate(malformed)


def test_validator_rejects_missing_dependency_target(valid_plan, registry):
    malformed = replace(
        valid_plan,
        dependencies=(GraphDependency("missing", "positioning"), valid_plan.dependencies[1]),
    )
    with pytest.raises(InvalidPlanError, match="missing dependency"):
        PlanValidator(registry).validate(malformed)


def test_validator_rejects_self_dependency(valid_plan, registry):
    malformed = replace(valid_plan, dependencies=(GraphDependency("market_analysis", "market_analysis"), *valid_plan.dependencies))
    with pytest.raises(InvalidPlanError, match="self-dependency"):
        PlanValidator(registry).validate(malformed)


def test_validator_rejects_cycle(valid_plan, registry):
    malformed = replace(valid_plan, dependencies=(*valid_plan.dependencies, GraphDependency("positioning", "market_analysis")))
    with pytest.raises(InvalidPlanError, match="cycle"):
        PlanValidator(registry).validate(malformed)


def test_validator_rejects_invalid_parallel_metadata(valid_plan, registry):
    positioning = replace(valid_plan.nodes[2], parallel_group="evidence_analysis", parallelizable=True)
    malformed = replace(valid_plan, nodes=(*valid_plan.nodes[:2], positioning))
    with pytest.raises(InvalidPlanError, match="parallel group"):
        PlanValidator(registry).validate(malformed)


def test_validator_rejects_output_mismatch(valid_plan, registry):
    node = replace(valid_plan.nodes[0], expected_outputs=(*valid_plan.nodes[0].expected_outputs, "not_registered"))
    with pytest.raises(InvalidPlanError, match="expected output"):
        PlanValidator(registry).validate(replace(valid_plan, nodes=(node, *valid_plan.nodes[1:])))


def test_validator_rejects_quality_gate_mismatch(valid_plan, registry):
    node = replace(valid_plan.nodes[0], quality_gate=("invented gate",))
    with pytest.raises(InvalidPlanError, match="quality gate"):
        PlanValidator(registry).validate(replace(valid_plan, nodes=(node, *valid_plan.nodes[1:])))


def test_validator_rejects_duplicate_or_excess_questions(planner, registry):
    blocked = planner.plan(interpretation(), PlanningContext())
    duplicate = replace(blocked, blocking_questions=(blocked.blocking_questions[0], blocked.blocking_questions[0]))
    with pytest.raises(InvalidPlanError, match="duplicate"):
        PlanValidator(registry).validate(duplicate)

    extra = BlockingQuestion("product_truth", "Provide product truth.", "positioning")
    excess = replace(blocked, blocking_questions=(*blocked.blocking_questions, extra))
    with pytest.raises(InvalidPlanError, match="more than three"):
        PlanValidator(registry).validate(excess)


def test_validator_rejects_question_for_known_input(planner, registry):
    blocked = planner.plan(interpretation(), PlanningContext())
    with pytest.raises(InvalidPlanError, match="known input"):
        PlanValidator(registry).validate(blocked, known_input_keys=frozenset({blocked.blocking_questions[0].input_key}))


def test_validator_rejects_executable_readiness_with_zero_bindings(valid_plan, registry):
    malformed = replace(valid_plan, execution_readiness=ExecutionReadiness.EXECUTABLE)
    with pytest.raises(InvalidPlanError, match="planning-only"):
        PlanValidator(registry).validate(malformed)


def test_validator_rejects_unsupported_scenario_graph(valid_plan, registry):
    malformed = replace(valid_plan, scenario_key="another_scenario")
    with pytest.raises(InvalidPlanError, match="unsupported scenario"):
        PlanValidator(registry).validate(malformed)
