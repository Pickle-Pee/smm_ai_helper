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
    InvalidContextValueError,
    InvalidPlanError,
    MarketingOrchestratorPlanner,
    PlanningContext,
    PlanningInputKey,
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


def fact(key, *, modules=(), scenarios=(SCENARIO,), value="known", authorized=True, sensitivity=Sensitivity.INTERNAL, label=None, fact_id=None, input_key=None, source="caller"):
    typed_key = input_key
    if typed_key is None and key in PlanningInputKey._value2member_map_:
        typed_key = PlanningInputKey(key)
    return AuthorizedContextFact(
        fact_id=fact_id or f"fact.{key}",
        label=label or key.replace("_", " ").title(),
        value=value,
        input_key=typed_key,
        module_relevance=frozenset(modules),
        scenario_relevance=frozenset(scenarios),
        source=source,
        evidence=(f"evidence:{key}",),
        confidence=0.9,
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
    caller_assumptions = ["Original"]
    context_fact = fact("product", value=source, fact_id="fact.product-deep-freeze")
    source["nested"].append("two")
    context = complete_context(known_facts=(context_fact, *complete_context().known_facts[1:]), assumptions=caller_assumptions)
    caller_assumptions.append("Mutated")
    plan = planner.plan(interpretation(), context)

    assert isinstance(context_fact.value, MappingProxyType)
    assert context_fact.value["nested"] == ("one",)
    assert context.assumptions == ("Original",)
    assert isinstance(plan.nodes, tuple)
    assert isinstance(plan.nodes[0].context_packet.known_facts, tuple)
    with pytest.raises(FrozenInstanceError):
        plan.planning_status = PlanningStatus.INVALID  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        plan.nodes.append(plan.nodes[0])  # type: ignore[attr-defined]


def test_descriptive_label_without_typed_input_key_does_not_satisfy_requirement(planner):
    prose = AuthorizedContextFact(
        fact_id="fact.prose-product",
        label="Product or category",
        value="known",
        input_key=None,
        scenario_relevance=frozenset({SCENARIO}),
        source="caller",
        confidence=0.9,
    )
    context = PlanningContext(known_facts=(prose,))

    plan = planner.plan(interpretation(), context)

    assert PlanningInputKey.PRODUCT_OR_CATEGORY in {item.input_key for item in plan.blocking_questions}


@pytest.mark.parametrize("raw_key", ["Product or category", "product_or_category"])
def test_raw_input_key_strings_are_rejected(raw_key):
    with pytest.raises(InvalidContextValueError, match="input_key"):
        AuthorizedContextFact(
            fact_id="fact.raw-key",
            label="Product",
            value="known",
            input_key=raw_key,  # type: ignore[arg-type]
            source="caller",
            confidence=0.9,
        )


def test_exact_typed_input_key_satisfies_requirement(planner):
    typed = fact("product_or_category")
    plan = planner.plan(interpretation(), PlanningContext(known_facts=(typed,)))
    assert PlanningInputKey.PRODUCT_OR_CATEGORY not in {item.input_key for item in plan.blocking_questions}


@pytest.mark.parametrize("fact_id", ["", "Product Fact", "fact/one"])
def test_fact_id_is_required_and_uses_stable_format(fact_id):
    with pytest.raises(InvalidContextValueError, match="fact_id"):
        AuthorizedContextFact(fact_id=fact_id, label="Product", value="known", source="caller", confidence=0.9)


def test_duplicate_fact_id_is_rejected():
    with pytest.raises(InvalidContextValueError, match="fact_id"):
        PlanningContext(known_facts=(fact("product"), fact("geographic_scope", fact_id="fact.product")))


def test_label_changes_do_not_change_matching_or_plan_identity(planner):
    first_fact = fact("product_or_category", label="Product or category")
    second_fact = fact("product_or_category", label="Completely different description")
    rest = complete_context().known_facts[1:]
    first = planner.plan(interpretation(), complete_context(known_facts=(first_fact, *rest)))
    second = planner.plan(interpretation(), complete_context(known_facts=(second_fact, *rest)))
    assert first.blocking_questions == second.blocking_questions
    assert first.plan_id == second.plan_id


def test_relevant_fact_identity_changes_plan_identity(planner):
    facts = complete_context().known_facts
    changed = replace(facts[0], fact_id="fact.product-or-category-v2")
    assert planner.plan(interpretation(), complete_context()).plan_id != planner.plan(
        interpretation(), complete_context(known_facts=(changed, *facts[1:]))
    ).plan_id


@pytest.mark.parametrize(
    ("factory", "field"),
    [
        (lambda: fact("product", source=[]), "source"),
        (lambda: PlanningContext(assumptions=(bytearray(b"x"),)), "assumptions"),
        (lambda: PlanningContext(constraints="not-a-sequence"), "constraints"),
        (lambda: replace(fact("product"), scenario_relevance="new_positioning_v1"), "scenario_relevance"),
        (lambda: replace(interpretation(), scenario_key=bytearray(b"bad")), "scenario_key"),
        (lambda: AuthorizedContextFact(fact_id="fact.bad", label="Bad", value="x", source="caller", evidence=({"mutable": True},), confidence=0.9), "evidence"),
        (lambda: AuthorizedContextFact(fact_id="fact.bad", label="Bad", value="x", source="caller", confidence=True), "confidence"),
        (lambda: AuthorizedContextFact(fact_id="fact.bad", label="Bad", value="x", source="caller", confidence=float("nan")), "confidence"),
        (lambda: AuthorizedContextFact(fact_id="fact.bad", label="Bad", value="x", source="caller", sensitivity="INTERNAL", confidence=0.9), "sensitivity"),
    ],
)
def test_invalid_metadata_fails_at_contract_boundary(factory, field):
    with pytest.raises(InvalidContextValueError, match=field):
        factory()


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
    scenario_fact = fact("product", scenarios=(SCENARIO,), fact_id="fact.product-scenario")
    market_fact = fact("market_only", modules=(ModuleId.MARKET_ANALYSIS,), scenarios=())
    unrelated = fact("unrelated", modules=(ModuleId.CREATOR,), scenarios=())
    unauthorized = fact("secret", scenarios=(SCENARIO,), authorized=False, sensitivity=Sensitivity.SECRET)
    context = complete_context(known_facts=(scenario_fact, market_fact, unrelated, unauthorized, *complete_context().known_facts[1:]))

    plan = planner.plan(interpretation(), context)
    market_keys = {item.fact_id for item in plan.nodes[0].context_packet.known_facts}
    competitor_keys = {item.fact_id for item in plan.nodes[1].context_packet.known_facts}

    assert "fact.product-scenario" in market_keys and "fact.product-scenario" in competitor_keys
    assert "fact.market_only" in market_keys and "fact.market_only" not in competitor_keys
    assert "fact.unrelated" not in market_keys | competitor_keys
    assert "fact.secret" not in market_keys | competitor_keys


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
        "competitor_analysis", "market_analysis"
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
    with pytest.raises(InvalidContextValueError, match="module_id"):
        replace(valid_plan.nodes[0], module_id="MARKET ANALYSIS")  # type: ignore[arg-type]


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

    extra = BlockingQuestion(PlanningInputKey.PRODUCT_TRUTH, "What verified product truth can support the position?", "positioning")
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


@pytest.mark.parametrize(
    "dependencies,dependency_refs",
    [
        ((GraphDependency("competitor_analysis", "positioning"),), ("competitor_analysis",)),
        ((GraphDependency("market_analysis", "positioning"),), ("market_analysis",)),
        ((), ()),
    ],
    ids=("missing-market-edge", "missing-competitor-edge", "both-edges-missing"),
)
def test_validator_rejects_each_missing_positioning_edge_independently(valid_plan, registry, dependencies, dependency_refs):
    positioning = replace(valid_plan.nodes[2], dependency_references=dependency_refs)
    malformed = replace(valid_plan, nodes=(*valid_plan.nodes[:2], positioning), dependencies=dependencies)
    with pytest.raises(InvalidPlanError, match="exact edge set"):
        PlanValidator(registry).validate(malformed)


def test_validator_rejects_extra_positioning_edge(valid_plan, registry):
    malformed = replace(
        valid_plan,
        dependencies=(*valid_plan.dependencies, GraphDependency("market_analysis", "competitor_analysis")),
    )
    with pytest.raises(InvalidPlanError):
        PlanValidator(registry).validate(malformed)


def test_validator_rejects_edge_without_node_dependency_reference(valid_plan, registry):
    positioning = replace(valid_plan.nodes[2], dependency_references=("competitor_analysis",))
    with pytest.raises(InvalidPlanError, match="dependency references"):
        PlanValidator(registry).validate(replace(valid_plan, nodes=(*valid_plan.nodes[:2], positioning)))


def test_validator_rejects_node_dependency_reference_without_edge(valid_plan, registry):
    malformed = replace(valid_plan, dependencies=(valid_plan.dependencies[0],))
    with pytest.raises(InvalidPlanError, match="dependency references"):
        PlanValidator(registry).validate(malformed)


def test_validator_rejects_wrong_deterministic_positioning_node_id(valid_plan, registry):
    market = replace(valid_plan.nodes[0], node_id="market")
    dependencies = (
        GraphDependency("competitor_analysis", "positioning"),
        GraphDependency("market", "positioning"),
    )
    positioning = replace(valid_plan.nodes[2], dependency_references=("competitor_analysis", "market"))
    malformed = replace(valid_plan, nodes=(market, valid_plan.nodes[1], positioning), dependencies=dependencies)
    with pytest.raises(InvalidPlanError, match="node IDs"):
        PlanValidator(registry).validate(malformed)


def test_correct_module_sequence_with_incorrect_topology_is_rejected(valid_plan, registry):
    nodes = tuple(replace(node, parallel_group=None, parallelizable=False) for node in valid_plan.nodes)
    with pytest.raises(InvalidPlanError, match="parallel membership"):
        PlanValidator(registry).validate(replace(valid_plan, nodes=nodes))


def test_unsupported_empty_plan_cannot_bypass_planning_only_readiness(planner, registry):
    unsupported = planner.plan(interpretation(scenario="future_scenario"), PlanningContext())
    with pytest.raises(InvalidPlanError, match="planning-only"):
        PlanValidator(registry).validate(replace(unsupported, execution_readiness=ExecutionReadiness.EXECUTABLE))


def test_plan_state_matrix_accepts_independently_declared_legal_states(planner, registry, valid_plan):
    blocked = planner.plan(interpretation(), PlanningContext())
    unsupported = planner.plan(interpretation(scenario="future_scenario"), PlanningContext())
    sufficient = replace(valid_plan, data_sufficiency=DataSufficiency.SUFFICIENT, limitations=())
    partial = valid_plan

    for plan in (sufficient, partial, blocked, unsupported):
        PlanValidator(registry).validate(plan)


@pytest.mark.parametrize(
    "mutation,message",
    [
        ({"planning_status": PlanningStatus.BLOCKED, "data_sufficiency": DataSufficiency.INSUFFICIENT, "stop_condition": PlanningStopCondition.BLOCKING_INPUT_MISSING, "blocking_questions": ()}, "requires blocking questions"),
        ({"planning_status": PlanningStatus.BLOCKED, "data_sufficiency": DataSufficiency.PARTIAL}, "insufficient data"),
        ({"planning_status": PlanningStatus.BLOCKED, "data_sufficiency": DataSufficiency.INSUFFICIENT, "stop_condition": PlanningStopCondition.PLAN_COMPLETE, "blocking_questions": (BlockingQuestion(PlanningInputKey.PRODUCT, "What product is being positioned?", "positioning"),)}, "blocking-input"),
        ({"planning_status": PlanningStatus.VALIDATED, "blocking_questions": (BlockingQuestion(PlanningInputKey.PRODUCT, "What product is being positioned?", "positioning"),)}, "cannot contain blocking"),
        ({"data_sufficiency": DataSufficiency.PARTIAL, "limitations": ()}, "explicit limitations"),
        ({"data_sufficiency": DataSufficiency.INSUFFICIENT}, "cannot have insufficient"),
        ({"data_sufficiency": DataSufficiency.SUFFICIENT, "stop_condition": PlanningStopCondition.BLOCKING_INPUT_MISSING}, "complete stop"),
        ({"stop_condition": PlanningStopCondition.UNSUPPORTED_SCENARIO}, "complete stop"),
        ({"planning_status": PlanningStatus.INVALID}, "raise validation errors"),
    ],
)
def test_plan_state_matrix_rejects_each_contradiction(valid_plan, registry, mutation, message):
    with pytest.raises(InvalidPlanError, match=message):
        PlanValidator(registry).validate(replace(valid_plan, **mutation))


def test_unsupported_state_rejects_supported_graph_and_wrong_stop(planner, valid_plan, registry):
    unsupported_graph = replace(
        valid_plan,
        planning_status=PlanningStatus.UNSUPPORTED,
        structural_validity=StructuralValidity.INVALID,
        data_sufficiency=DataSufficiency.INSUFFICIENT,
        stop_condition=PlanningStopCondition.UNSUPPORTED_SCENARIO,
        limitations=("unsupported",),
    )
    with pytest.raises(InvalidPlanError, match="cannot contain a supported graph"):
        PlanValidator(registry).validate(unsupported_graph)

    unsupported = planner.plan(interpretation(scenario="future_scenario"), PlanningContext())
    with pytest.raises(InvalidPlanError, match="unsupported stop"):
        PlanValidator(registry).validate(replace(unsupported, stop_condition=PlanningStopCondition.PLAN_COMPLETE))


def test_single_module_does_not_interpret_registry_prose_as_input_keys(planner):
    plan = planner.plan(interpretation(module="MARKET_ANALYSIS"), PlanningContext())

    assert plan.blocking_questions == ()
    assert plan.nodes[0].scoped_inputs == ()
    assert plan.data_sufficiency is DataSufficiency.PARTIAL
    assert plan.limitations
    assert all("market size" not in item.casefold() for item in plan.limitations)
    source = Path("app/marketing_orchestrator/planner.py").read_text(encoding="utf-8")
    assert "blocking_for_strong_conclusion" not in source.casefold()


def test_every_generated_question_uses_an_approved_missing_typed_requirement(planner):
    plan = planner.plan(interpretation(), PlanningContext())

    for question in plan.blocking_questions:
        node = next(node for node in plan.nodes if node.node_id == question.node_id)
        scoped = next(item for item in node.scoped_inputs if item.requirement.key is question.input_key)
        assert scoped.present is False
        assert scoped.requirement.question_template == question.question
        assert scoped.requirement.scenario_key == SCENARIO


def test_plan_identity_uses_only_effective_scoped_context(planner):
    baseline = planner.plan(interpretation(), complete_context())
    creator_only = fact("creator_only", modules=(ModuleId.CREATOR,), scenarios=(), value="ignored")
    unauthorized = fact("unauthorized", value="ignored", authorized=False)
    changed_context = complete_context(known_facts=(*complete_context().known_facts, creator_only, unauthorized))
    changed = planner.plan(interpretation(), changed_context)

    assert changed.plan_id == baseline.plan_id
    assert tuple(node.context_packet for node in changed.nodes) == tuple(node.context_packet for node in baseline.nodes)


def test_plan_identity_is_order_independent_but_relevant_content_sensitive(planner):
    facts = complete_context().known_facts
    baseline = planner.plan(interpretation(), complete_context(known_facts=facts))
    reordered = planner.plan(interpretation(), complete_context(known_facts=tuple(reversed(facts))))
    changed_fact = fact(REQUIRED_POSITIONING_KEYS[0], value="changed")
    changed = planner.plan(interpretation(), complete_context(known_facts=(changed_fact, *facts[1:])))
    removed = planner.plan(interpretation(), complete_context(known_facts=facts[1:]))

    assert reordered.plan_id == baseline.plan_id
    assert changed.plan_id != baseline.plan_id
    assert removed.plan_id != baseline.plan_id


def test_plan_identity_canonicalizes_nested_mapping_order(planner):
    first_value = {"b": [2, 3], "a": {"y": True, "x": None}}
    second_value = {"a": {"x": None, "y": True}, "b": [2, 3]}
    base_facts = complete_context().known_facts
    first = planner.plan(
        interpretation(),
        complete_context(known_facts=(fact(REQUIRED_POSITIONING_KEYS[0], value=first_value), *base_facts[1:])),
    )
    second = planner.plan(
        interpretation(),
        complete_context(known_facts=(fact(REQUIRED_POSITIONING_KEYS[0], value=second_value), *base_facts[1:])),
    )
    assert first.plan_id == second.plan_id


def test_context_values_are_recursively_frozen_without_caller_references():
    source = {"z": [1, {"nested": [2]}], "a": {"value": True}}
    context_fact = fact("product", value=source)
    source["z"][1]["nested"].append(3)
    source["a"]["value"] = False

    assert tuple(context_fact.value) == ("a", "z")
    assert context_fact.value["z"] == (1, MappingProxyType({"nested": (2,)}))
    with pytest.raises(TypeError):
        context_fact.value["new"] = "no"  # type: ignore[index]


@pytest.mark.parametrize(
    "value",
    [
        bytearray(b"mutable"),
        {"unordered"},
        {1: "non-string key"},
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_context_values_reject_noncanonical_or_mutable_values(value):
    with pytest.raises(InvalidContextValueError):
        fact("product", value=value)


def test_context_values_reject_custom_mutable_objects():
    class Mutable:
        pass

    with pytest.raises(InvalidContextValueError):
        fact("product", value=Mutable())


def test_upstream_finding_uses_the_same_immutable_value_contract():
    source = {"items": ["one"]}
    finding = UpstreamFinding("market_analysis", "segments", source)
    source["items"].append("two")
    assert finding.value["items"] == ("one",)
    with pytest.raises(InvalidContextValueError):
        UpstreamFinding("market_analysis", "segments", bytearray(b"mutable"))
