from __future__ import annotations

from app.module_registry import ModuleAvailabilityStatus, ModuleId, ModuleRegistry

from .contracts import (
    DataSufficiency,
    ExecutionReadiness,
    OrchestrationPlan,
    PlanningInputKey,
    PlanningStatus,
    PlanningStopCondition,
    StructuralValidity,
)
from .errors import InvalidPlanError


SUPPORTED_SCENARIOS = frozenset({"explicit_single_module_v1", "new_positioning_v1"})
_POSITIONING_NODE_MODULES = (
    ("market_analysis", ModuleId.MARKET_ANALYSIS),
    ("competitor_analysis", ModuleId.COMPETITOR_ANALYSIS),
    ("positioning", ModuleId.POSITIONING),
)
_POSITIONING_EDGES = (
    ("competitor_analysis", "positioning"),
    ("market_analysis", "positioning"),
)


class PlanValidator:
    def __init__(self, registry: ModuleRegistry) -> None:
        self._registry = registry

    def validate(self, plan: OrchestrationPlan, *, known_input_keys: frozenset[PlanningInputKey] = frozenset()) -> None:
        self._validate_global_invariants(plan)
        if plan.scenario_key not in SUPPORTED_SCENARIOS:
            if plan.planning_status is PlanningStatus.UNSUPPORTED:
                return
            raise InvalidPlanError("unsupported scenario graph")

        ids = [node.node_id for node in plan.nodes]
        if len(ids) != len(set(ids)):
            raise InvalidPlanError("duplicate node ID")
        if ids != self._topological_order(plan):
            raise InvalidPlanError("node ordering is not deterministic topological order")
        node_by_id = {node.node_id: node for node in plan.nodes}

        for node in plan.nodes:
            if type(node.module_id) is not ModuleId:
                raise InvalidPlanError("final node contains unresolved alias or unknown module")
            try:
                descriptor = self._registry.get(node.module_id)
            except LookupError as exc:
                raise InvalidPlanError("unknown module") from exc
            if not set(node.expected_outputs) <= set(descriptor.outputs):
                raise InvalidPlanError("expected output is incompatible with descriptor")
            if not set(node.quality_gate) <= set(descriptor.quality_gate):
                raise InvalidPlanError("quality gate is incompatible with descriptor")
            priorities = [item.requirement.priority for item in node.scoped_inputs]
            if priorities != sorted(priorities) or len(priorities) != len(set(priorities)):
                raise InvalidPlanError("input requirement ordering is not deterministic")
            for item in node.scoped_inputs:
                requirement = item.requirement
                if requirement.module_id is not node.module_id or requirement.scenario_key != plan.scenario_key:
                    raise InvalidPlanError("input requirement is outside its approved module or scenario")
            incoming = tuple(edge.upstream_node_id for edge in plan.dependencies if edge.downstream_node_id == node.node_id)
            if node.dependency_references != incoming:
                raise InvalidPlanError("node dependency references do not match graph edges")

        expected_edges = sorted(
            plan.dependencies,
            key=lambda edge: (edge.downstream_node_id, edge.upstream_node_id),
        )
        if list(plan.dependencies) != expected_edges:
            raise InvalidPlanError("dependency ordering is not deterministic")
        for edge in plan.dependencies:
            if edge.upstream_node_id not in node_by_id or edge.downstream_node_id not in node_by_id:
                raise InvalidPlanError("missing dependency target")
            if edge.upstream_node_id == edge.downstream_node_id:
                raise InvalidPlanError("self-dependency")
            upstream = node_by_id[edge.upstream_node_id]
            downstream = node_by_id[edge.downstream_node_id]
            if upstream.parallel_group and upstream.parallel_group == downstream.parallel_group:
                raise InvalidPlanError("dependent nodes cannot share a parallel group")

        questions = plan.blocking_questions
        if len(questions) > 3:
            raise InvalidPlanError("more than three blocking questions")
        question_keys = [item.input_key.value.casefold() for item in questions]
        if len(question_keys) != len(set(question_keys)):
            raise InvalidPlanError("duplicate blocking question")
        if len({item.question for item in questions}) != len(questions):
            raise InvalidPlanError("duplicate blocking question")
        if {item.input_key for item in questions} & known_input_keys:
            raise InvalidPlanError("blocking question asks for known input")
        for question in questions:
            node = node_by_id.get(question.node_id)
            if node is None:
                raise InvalidPlanError("blocking question targets unknown node")
            matching = [item for item in node.scoped_inputs if item.requirement.key is question.input_key]
            if not matching or matching[0].present or matching[0].classification.value not in {"REQUIRED", "BLOCKING"}:
                raise InvalidPlanError("invalid blocking dependency")
            if matching[0].requirement.question_template != question.question:
                raise InvalidPlanError("blocking question is not the approved deterministic template")

        if plan.scenario_key == "explicit_single_module_v1":
            self._validate_single_module(plan)
        if plan.scenario_key == "new_positioning_v1":
            self._validate_positioning_topology(plan)

    def _validate_global_invariants(self, plan: OrchestrationPlan) -> None:
        if plan.execution_readiness is not ExecutionReadiness.PLANNING_ONLY:
            raise InvalidPlanError("Registry 1.0.0 plans must remain planning-only")
        if any(
            item.execution_binding is not None
            or item.availability_status is not ModuleAvailabilityStatus.METADATA_ONLY
            for item in self._registry.descriptors
        ):
            raise InvalidPlanError("planning foundation requires zero execution bindings")
        if len(plan.blocking_questions) > 3:
            raise InvalidPlanError("more than three blocking questions")
        question_keys = [item.input_key.value for item in plan.blocking_questions]
        if len(question_keys) != len(set(question_keys)) or len({item.question for item in plan.blocking_questions}) != len(plan.blocking_questions):
            raise InvalidPlanError("duplicate blocking question")

        if plan.planning_status is PlanningStatus.INVALID:
            raise InvalidPlanError("invalid plans raise validation errors")
        if plan.planning_status is PlanningStatus.BLOCKED:
            if plan.structural_validity is not StructuralValidity.VALID:
                raise InvalidPlanError("blocked plan must have valid structure")
            if plan.data_sufficiency is not DataSufficiency.INSUFFICIENT:
                raise InvalidPlanError("blocked plan requires insufficient data")
            if plan.stop_condition is not PlanningStopCondition.BLOCKING_INPUT_MISSING:
                raise InvalidPlanError("blocked plan requires blocking-input stop condition")
            if not plan.blocking_questions:
                raise InvalidPlanError("blocked plan requires blocking questions")
        elif plan.planning_status is PlanningStatus.VALIDATED:
            if plan.structural_validity is not StructuralValidity.VALID:
                raise InvalidPlanError("validated plan must have valid structure")
            if plan.data_sufficiency not in {DataSufficiency.SUFFICIENT, DataSufficiency.PARTIAL}:
                raise InvalidPlanError("validated plan cannot have insufficient data")
            if plan.stop_condition is not PlanningStopCondition.PLAN_COMPLETE:
                raise InvalidPlanError("validated plan requires complete stop condition")
            if plan.blocking_questions:
                raise InvalidPlanError("validated plan cannot contain blocking questions")
            if plan.data_sufficiency is DataSufficiency.PARTIAL and not plan.limitations:
                raise InvalidPlanError("partial data requires explicit limitations")
        elif plan.planning_status is PlanningStatus.UNSUPPORTED:
            if plan.structural_validity is not StructuralValidity.INVALID:
                raise InvalidPlanError("unsupported result must declare invalid structure")
            if plan.data_sufficiency is not DataSufficiency.INSUFFICIENT:
                raise InvalidPlanError("unsupported result requires insufficient data")
            if plan.stop_condition is not PlanningStopCondition.UNSUPPORTED_SCENARIO:
                raise InvalidPlanError("unsupported result requires unsupported stop condition")
            if plan.nodes or plan.dependencies:
                raise InvalidPlanError("unsupported result cannot contain a supported graph")
            if plan.blocking_questions:
                raise InvalidPlanError("unsupported result cannot contain blocking questions")
            if not plan.limitations:
                raise InvalidPlanError("unsupported result requires an explicit limitation")
        else:
            raise InvalidPlanError("unknown planning status")

        if plan.data_sufficiency is DataSufficiency.SUFFICIENT and plan.stop_condition is PlanningStopCondition.BLOCKING_INPUT_MISSING:
            raise InvalidPlanError("sufficient data cannot use missing-input stop condition")

    @staticmethod
    def _validate_single_module(plan: OrchestrationPlan) -> None:
        if len(plan.nodes) != 1 or plan.dependencies:
            raise InvalidPlanError("invalid explicit single-module graph")
        node = plan.nodes[0]
        if node.node_id != node.module_id.value.casefold():
            raise InvalidPlanError("invalid explicit single-module node ID")
        if node.dependency_references or node.parallel_group or node.parallelizable:
            raise InvalidPlanError("explicit single-module plan cannot declare dependencies or parallel metadata")

    @staticmethod
    def _validate_positioning_topology(plan: OrchestrationPlan) -> None:
        actual_nodes = tuple((node.node_id, node.module_id) for node in plan.nodes)
        if actual_nodes != _POSITIONING_NODE_MODULES:
            raise InvalidPlanError("invalid new-positioning node IDs or module mapping")
        actual_edges = tuple((edge.upstream_node_id, edge.downstream_node_id) for edge in plan.dependencies)
        if actual_edges != _POSITIONING_EDGES:
            raise InvalidPlanError("invalid new-positioning exact edge set")
        market, competitor, positioning = plan.nodes
        if (
            market.parallel_group != "evidence_analysis"
            or competitor.parallel_group != "evidence_analysis"
            or not market.parallelizable
            or not competitor.parallelizable
            or positioning.parallel_group is not None
            or positioning.parallelizable
        ):
            raise InvalidPlanError("invalid new-positioning parallel membership")
        if market.dependency_references or competitor.dependency_references:
            raise InvalidPlanError("upstream positioning nodes cannot declare dependencies")
        if positioning.dependency_references != ("competitor_analysis", "market_analysis"):
            raise InvalidPlanError("positioning must depend sequentially on both upstream nodes")

    @staticmethod
    def _topological_order(plan: OrchestrationPlan) -> list[str]:
        ids = [node.node_id for node in plan.nodes]
        indegree = {node_id: 0 for node_id in ids}
        outgoing = {node_id: [] for node_id in ids}
        for edge in plan.dependencies:
            if edge.upstream_node_id not in indegree or edge.downstream_node_id not in indegree:
                raise InvalidPlanError("missing dependency target")
            if edge.upstream_node_id == edge.downstream_node_id:
                raise InvalidPlanError("self-dependency")
            indegree[edge.downstream_node_id] += 1
            outgoing[edge.upstream_node_id].append(edge.downstream_node_id)
        result: list[str] = []
        remaining = [item for item in ids if indegree[item] == 0]
        while remaining:
            node_id = min(remaining, key=ids.index)
            remaining.remove(node_id)
            result.append(node_id)
            for target in sorted(outgoing[node_id], key=ids.index):
                indegree[target] -= 1
                if indegree[target] == 0:
                    remaining.append(target)
        if len(result) != len(ids):
            raise InvalidPlanError("dependency cycle")
        return result
