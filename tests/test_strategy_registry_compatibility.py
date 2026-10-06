"""Registry-owned compilation contracts and replay independent of planner key lists."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from app.marketing_orchestrator import MarketingOrchestratorPlanner, PlanningContext, RequestInterpretation
from app.module_registry import InputRequirement, ModuleId, ModuleRegistry
from app.module_execution.executors import build_module_executor_registry
from app.orchestration_runtime import PlanCompiler
from app.orchestration_runtime.compiler import validate_compiled_plan
from app.orchestration_runtime.errors import CompilationError
from app.orchestration_runtime.serialization import bounded, fingerprint, plan_from_json, plan_to_json
from tests.test_module_executors import fact, analyzer
from tests.test_strategy_builder import StrategyModel


FACTUAL_KEYS = ("business_goal", "product", "target_or_target_hypothesis", "product_truth")
SEEDS = ("customer_job_or_need", "relevant_alternative")


def source(*, seeds=True, missing=()):
    keys = (*FACTUAL_KEYS, *(SEEDS if seeds else ()))
    return MarketingOrchestratorPlanner().plan(RequestInterpretation(
        requested_output="strategy", decision_goal="Fill kindergarten groups", business_goal="UNSPECIFIED",
        intent="MARKETING_STRATEGY", object="product", depth="bounded", mode="PLANNING_ONLY",
        scenario_key="strategy_builder_v1"), PlanningContext(known_facts=tuple(
            fact(k, "Explicit " + k, scenario_relevance=frozenset({"strategy_builder_v1"}))
            for k in keys if k not in missing)))


def executors():
    # Same exact executor inventory can replay each compatible declared version.
    return build_module_executor_registry(model_call=StrategyModel(), analyzer=analyzer(),
                                         market_analyzer=analyzer(), registry_version="1.3.0")


def resign(plan):
    raw = bounded(plan)
    raw.pop("execution_fingerprint")
    return replace(plan, execution_fingerprint=fingerprint(raw))


def test_frozen_legacy_strategy_roundtrips_with_original_fingerprint():
    raw = json.loads((Path(__file__).parent / "fixtures/strategy_registry_v1_2.json").read_text(encoding="utf-8"))
    plan = plan_from_json(raw)
    assert plan.registry_version == "1.2.0"
    assert plan.execution_fingerprint == "97e10b3f1741995fbfee4002304df2cf5e1b44989683398db649f0b3b0d97b7f"
    assert plan_to_json(plan) == raw
    validate_compiled_plan(plan, executors())


def test_new_strategy_compiles_without_seeds_and_replays_its_declared_version():
    plan = PlanCompiler(ModuleRegistry.load("1.3.0"), executors()).compile(source(seeds=False))
    assert plan.registry_version == "1.3.0"
    assert plan_from_json(plan_to_json(plan)) == plan
    for node in plan.nodes:
        assert not set(SEEDS) & {f.label for f in node.context_packet.known_facts}
    validate_compiled_plan(plan, executors())


@pytest.mark.parametrize("missing", FACTUAL_KEYS)
def test_new_strategy_factual_keys_remain_blocking_for_compile_and_replay(missing):
    inventory = executors()
    with pytest.raises(CompilationError):
        PlanCompiler(ModuleRegistry.load("1.3.0"), inventory).compile(source(seeds=False, missing=(missing,)))
    good = PlanCompiler(ModuleRegistry.load("1.3.0"), inventory).compile(source())
    target = ModuleId.VIRTUAL_CMO if missing == "business_goal" else ModuleId.POSITIONING
    changed = replace(good, nodes=tuple(replace(node, context_packet=replace(node.context_packet,
        known_facts=tuple(f for f in node.context_packet.known_facts if f.label != missing),
        relevant_project_context=tuple(f for f in node.context_packet.relevant_project_context if f.label != missing),
    )) if node.module_id is target else node for node in good.nodes))
    with pytest.raises(CompilationError, match="first-party context"):
        validate_compiled_plan(resign(changed), inventory)


def test_legacy_strategy_requires_seeds_even_when_new_planner_keys_are_relaxed(monkeypatch):
    import app.marketing_orchestrator.strategy as strategy

    monkeypatch.setattr(strategy, "REQUIRED_KEYS", FACTUAL_KEYS)
    inventory = executors()
    compiler = PlanCompiler(ModuleRegistry.load("1.2.0"), inventory)
    with pytest.raises(CompilationError):
        compiler.compile(source(seeds=False))
    legacy = compiler.compile(source())
    assert legacy.registry_version == "1.2.0"
    assert plan_from_json(plan_to_json(legacy)) == legacy
    validate_compiled_plan(legacy, inventory)
    stripped = replace(legacy, nodes=tuple(replace(n, context_packet=replace(n.context_packet,
        known_facts=tuple(f for f in n.context_packet.known_facts if f.label not in SEEDS),
        relevant_project_context=tuple(f for f in n.context_packet.relevant_project_context if f.label not in SEEDS),
    )) for n in legacy.nodes))
    with pytest.raises(CompilationError, match="first-party context"):
        validate_compiled_plan(resign(stripped), inventory)
    relaxed = PlanCompiler(ModuleRegistry.load("1.3.0"), inventory).compile(source(seeds=False))
    with pytest.raises(CompilationError, match="first-party context"):
        validate_compiled_plan(resign(replace(relaxed, registry_version="1.2.0")), inventory)


@pytest.mark.parametrize("version", ["1.2.0", "1.3.0"])
@pytest.mark.parametrize("mutation", ["purpose", "other_inputs", "positioning_inputs", "outputs", "quality_gate"])
def test_metadata_compatibility_exemption_is_narrow(version, mutation):
    registry = ModuleRegistry.load(version)
    target = ModuleId.VIRTUAL_CMO if mutation == "other_inputs" else ModuleId.POSITIONING
    def change(d):
        if d.module_id is not target:
            return d
        if mutation in {"other_inputs", "positioning_inputs"}:
            return replace(d, inputs={**d.inputs, InputRequirement.OPTIONAL: ("unapproved_input",)})
        if mutation == "purpose":
            return replace(d, purpose="unapproved")
        return replace(d, **{mutation: (*getattr(d, mutation), "unapproved")})
    changed = ModuleRegistry(version=version, descriptors=tuple(change(d) for d in registry.descriptors))
    with pytest.raises(CompilationError):
        PlanCompiler(changed, executors()).compile(source())
