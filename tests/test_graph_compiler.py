import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import copy

import pytest

from app.marketing_orchestrator.contracts import ExecutionReadiness, Sensitivity, PlanningStatus, StructuralValidity, PlanningStopCondition, GraphDependency
from app.module_execution import ModuleExecutionRequest, ModuleExecutorDispatcher, ModuleExecutorRegistry
from app.module_registry import ModuleRegistry
from app.orchestration_runtime import PlanCompiler
from app.orchestration_runtime.contracts import artifact_key, module_job_id
from app.orchestration_runtime.errors import RuntimeContractError, CompilationError
from app.orchestration_runtime.serialization import plan_to_json, plan_from_json, result_to_json, result_from_json
from tests.graph_fakes import compiled, registry, source_plan


def test_competitive_scenario_is_planning_only_and_compiles_immutably():
    source = source_plan()
    result = compiled()
    assert source.execution_readiness is ExecutionReadiness.PLANNING_ONLY
    assert [n.node_id for n in result.nodes] == ["competitor_analysis", "positioning"]
    assert result.nodes[1].dependency_node_ids == ("competitor_analysis",)
    assert result == plan_from_json(plan_to_json(result)) == compiled()
    assert not hasattr(source.nodes[0], "status")
    assert artifact_key("run", 1, "positioning") != artifact_key("run", 2, "positioning")
    assert module_job_id("run", 1, "positioning") != module_job_id("run", 2, "positioning")


@pytest.mark.parametrize("change", [
    lambda p: source_plan("new_positioning_v1"),
    lambda p: replace(p, planning_status=PlanningStatus.BLOCKED),
    lambda p: replace(p, structural_validity=StructuralValidity.INVALID),
    lambda p: replace(p, stop_condition=PlanningStopCondition.BLOCKING_INPUT_MISSING),
    lambda p: replace(p, scenario_key="unknown"),
    lambda p: replace(p, dependencies=(GraphDependency("positioning", "competitor_analysis"),)),
    lambda p: replace(p, nodes=(replace(p.nodes[0], expected_outputs=("unknown",)), *p.nodes[1:])),
    lambda p: replace(p, nodes=(replace(p.nodes[0], quality_gate=()), *p.nodes[1:])),
    lambda p: replace(p, nodes=(replace(p.nodes[0], node_id="bad:step"), *p.nodes[1:])),
    lambda p: replace(p, nodes=(replace(p.nodes[0], node_id="a" * 65), *p.nodes[1:])),
    lambda p: replace(p, nodes=(replace(p.nodes[0], objective="x" * 1_048_577), *p.nodes[1:])),
])
def test_compiler_fail_closed(change):
    with pytest.raises(CompilationError):
        PlanCompiler(ModuleRegistry.load("1.1.0"), registry()).compile(change(source_plan()))


def test_secret_missing_executor_and_default_registry_rejected_before_persistence():
    source = source_plan()
    packet = source.nodes[0].context_packet
    facts = (replace(packet.known_facts[0], sensitivity=Sensitivity.SECRET), *packet.known_facts[1:])
    secret = replace(source, nodes=(replace(source.nodes[0], context_packet=replace(packet, known_facts=facts)), *source.nodes[1:]))
    for plan, metadata, executors in (
        (secret, ModuleRegistry.load("1.1.0"), registry()),
        (source, ModuleRegistry.load("1.1.0"), ModuleExecutorRegistry()),
        (source, ModuleRegistry.load(), registry()),
    ):
        with pytest.raises(CompilationError):
            PlanCompiler(metadata, executors).compile(plan)


def test_start_revalidates_before_opening_session():
    from app.orchestration_runtime.service import GraphExecutionService
    def forbidden():
        pytest.fail("ineligible start opened a database session")
    good = compiled()
    for plan, executors in ((replace(good, registry_version="1.0.0"), registry()),
                            (good, ModuleExecutorRegistry())):
        service = GraphExecutionService(forbidden, executors=executors)
        with pytest.raises((RuntimeContractError, LookupError)):
            asyncio.run(service.start_compiled_run(owner_id=1, run_id="no-writes", plan=plan))


def test_descriptor_and_executor_metadata_mismatch_fail_compilation():
    metadata = ModuleRegistry.load("1.1.0")
    changed = ModuleRegistry(version="1.1.0", descriptors=tuple(
        replace(d, purpose="changed purpose") if d.module_id.value == "COMPETITOR_ANALYSIS" else d
        for d in metadata.descriptors))
    with pytest.raises(CompilationError):
        PlanCompiler(changed, registry()).compile(source_plan())
    real = registry()
    for attr, value in (("module_id", real.resolve("positioning.v1").module_id), ("contract_version", "unknown.v1")):
        wrong = registry().resolve("competitor_analysis.v1")
        setattr(wrong, attr, value)
        executors = ModuleExecutorRegistry((wrong, real.resolve("positioning.v1")))
        with pytest.raises(CompilationError):
            PlanCompiler(metadata, executors).compile(source_plan())


def test_failed_compilation_has_zero_persistence_calls():
    from app.marketing_orchestrator import MarketingOrchestratorPlanner, PlanningContext, RequestInterpretation
    from app.orchestration_runtime.service import GraphExecutionService
    from unittest.mock import Mock
    sessions = Mock(side_effect=AssertionError("database must remain untouched"))
    blocked = MarketingOrchestratorPlanner().plan(RequestInterpretation(
        requested_output="positioning", decision_goal="position", business_goal="sales", intent="position",
        object="product", depth="bounded", mode="workflow", scenario_key="competitive_positioning_v1",
    ), PlanningContext())
    assert blocked.blocking_questions and blocked.planning_status is PlanningStatus.BLOCKED
    source = source_plan()
    packet = source.nodes[0].context_packet
    secret = replace(source, nodes=(replace(source.nodes[0], context_packet=replace(packet, known_facts=(
        replace(packet.known_facts[0], sensitivity=Sensitivity.SECRET), *packet.known_facts[1:],
    ))), *source.nodes[1:]))
    async def start(plan, executors):
        compiled_plan = PlanCompiler(ModuleRegistry.load("1.1.0"), executors).compile(plan)
        await GraphExecutionService(sessions, executors=executors).start_compiled_run(
            owner_id=1, run_id="not-created", plan=compiled_plan)
    for plan, executors in ((blocked, registry()), (source_plan("new_positioning_v1"), registry()),
                            (secret, registry()), (source, ModuleExecutorRegistry())):
        with pytest.raises(CompilationError):
            asyncio.run(start(plan, executors))
    sessions.assert_not_called()


def test_no_production_ingress_imports_graph_runtime():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for directory in (root / "app", root / "bot"):
        for path in directory.rglob("*.py"):
            if "orchestration_runtime" not in path.parts:
                assert "orchestration_runtime" not in path.read_text(encoding="utf-8"), path


def test_persisted_plan_tampering_unknown_fields_and_secret_rejected():
    raw = plan_to_json(compiled())
    for mutate in (lambda r: r.update(extra=True), lambda r: r.update(registry_version="1.0.0"),
                   lambda r: r["nodes"][0].update(objective="tampered"),
                   lambda r: r["nodes"][0]["context_packet"]["known_facts"][0].update(sensitivity="SECRET")):
        corrupt = copy.deepcopy(raw)
        mutate(corrupt)
        with pytest.raises(RuntimeContractError):
            plan_from_json(corrupt)


def test_execution_result_roundtrip_includes_typed_provenance_and_timestamps():
    executors = registry()
    node = compiled(executors).nodes[0]
    result = asyncio.run(ModuleExecutorDispatcher(executors).dispatch(node.binding, ModuleExecutionRequest(
        execution_id="roundtrip", module_id=node.module_id, objective=node.objective,
        expected_outputs=node.expected_outputs, context_packet=node.context_packet,
    )))
    normalized = result.normalized_result
    evidence = tuple(replace(e, observed_at=datetime(2026, 9, 17, tzinfo=timezone.utc)) for e in normalized.evidence)
    result = replace(result, payload=result_to_json(result)["payload"], normalized_result=replace(normalized, evidence=evidence))
    raw = result_to_json(result)
    restored = result_from_json(raw)
    assert restored == result
    assert result_to_json(restored) == raw
    for mutate in (lambda r: r.update(extra=1), lambda r: r.update(schema_version="unknown.v2"),
                   lambda r: r["normalized_result"].update(module_status="UNKNOWN"),
                   lambda r: r["normalized_result"]["evidence"][0].update(observed_at="2026-01-01")):
        corrupt = copy.deepcopy(raw)
        mutate(corrupt)
        with pytest.raises(RuntimeContractError):
            result_from_json(corrupt)
