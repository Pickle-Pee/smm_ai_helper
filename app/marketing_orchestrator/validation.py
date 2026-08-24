from __future__ import annotations

from app.module_registry import ModuleAvailabilityStatus, ModuleId, ModuleRegistry

from .contracts import ExecutionReadiness, OrchestrationPlan, PlanningStatus, StructuralValidity
from .errors import InvalidPlanError


SUPPORTED_SCENARIOS = frozenset({"explicit_single_module_v1", "new_positioning_v1"})


class PlanValidator:
    def __init__(self, registry: ModuleRegistry) -> None:
        self._registry = registry

    def validate(self, plan: OrchestrationPlan, *, known_input_keys: frozenset[str] = frozenset()) -> None:
        if plan.scenario_key not in SUPPORTED_SCENARIOS:
            if plan.planning_status is PlanningStatus.UNSUPPORTED and not plan.nodes and not plan.dependencies:
                return
            raise InvalidPlanError("unsupported scenario graph")
        if plan.structural_validity is not StructuralValidity.VALID:
            raise InvalidPlanError("usable plan must declare valid structure")
        if plan.execution_readiness is not ExecutionReadiness.PLANNING_ONLY:
            raise InvalidPlanError("Registry 1.0.0 plans must remain planning-only")
        if any(item.execution_binding is not None or item.availability_status is not ModuleAvailabilityStatus.METADATA_ONLY for item in self._registry.descriptors):
            raise InvalidPlanError("planning foundation requires zero execution bindings")

        ids = [node.node_id for node in plan.nodes]
        if len(ids) != len(set(ids)):
            raise InvalidPlanError("duplicate node ID")
        if ids != self._topological_order(plan):
            raise InvalidPlanError("node ordering is not deterministic topological order")
        node_by_id = {node.node_id: node for node in plan.nodes}

        for node in plan.nodes:
            if not isinstance(node.module_id, ModuleId):
                raise InvalidPlanError("final node contains unresolved alias or unknown module")
            try:
                descriptor = self._registry.get(node.module_id)
            except LookupError as exc:
                raise InvalidPlanError("unknown module") from exc
            if not set(node.expected_outputs) <= set(descriptor.outputs):
                raise InvalidPlanError("expected output is incompatible with descriptor")
            if not set(node.quality_gate) <= set(descriptor.quality_gate):
                raise InvalidPlanError("quality gate is incompatible with descriptor")
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
        question_keys = [item.input_key.casefold() for item in questions]
        if len(question_keys) != len(set(question_keys)):
            raise InvalidPlanError("duplicate blocking question")
        if set(question_keys) & {item.casefold() for item in known_input_keys}:
            raise InvalidPlanError("blocking question asks for known input")
        for question in questions:
            node = node_by_id.get(question.node_id)
            if node is None:
                raise InvalidPlanError("blocking question targets unknown node")
            matching = [item for item in node.scoped_inputs if item.key.casefold() == question.input_key.casefold()]
            if not matching or matching[0].present or matching[0].classification.value not in {"REQUIRED", "BLOCKING"}:
                raise InvalidPlanError("invalid blocking dependency")

        if plan.scenario_key == "explicit_single_module_v1" and (len(plan.nodes) != 1 or plan.dependencies):
            raise InvalidPlanError("invalid explicit single-module graph")
        if plan.scenario_key == "new_positioning_v1":
            expected_modules = (ModuleId.MARKET_ANALYSIS, ModuleId.COMPETITOR_ANALYSIS, ModuleId.POSITIONING)
            if tuple(node.module_id for node in plan.nodes) != expected_modules:
                raise InvalidPlanError("invalid new-positioning module graph")

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
