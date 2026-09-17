"""Pure, fail-closed compilation; no persistence or executor invocation."""
from dataclasses import replace
import re

from app.marketing_orchestrator.contracts import (
    OrchestrationPlan, PlanningStatus, PlanningStopCondition, Sensitivity, StructuralValidity,
)
from app.marketing_orchestrator.validation import PlanValidator
from app.module_registry import ModuleAvailabilityStatus, ModuleId, ModuleRegistry
from app.module_execution.contracts import MODULE_EXECUTION_CONTRACT_VERSION
from .contracts import CompiledExecutionNode, CompiledExecutionPlan, EXECUTABLE_SCENARIOS, PLAN_SCHEMA, validate_identity
from .errors import CompilationError, RuntimeContractError
from .serialization import bounded, fingerprint


def _binding(node, registry, executors=None):
    descriptor = registry.get(node.module_id)
    if descriptor.availability_status is not ModuleAvailabilityStatus.EXECUTION_BOUND or descriptor.execution_binding is None:
        raise CompilationError("module has no execution binding")
    binding = descriptor.execution_binding
    if binding != node.binding or binding.contract_version != MODULE_EXECUTION_CONTRACT_VERSION:
        raise CompilationError("execution binding mismatch")
    if not node.expected_outputs or len(set(node.expected_outputs)) != len(node.expected_outputs) or not set(node.expected_outputs) <= set(descriptor.outputs):
        raise CompilationError("incompatible expected outputs")
    if executors is not None:
        executor = executors.resolve(binding.executor_key)
        if executor.module_id is not node.module_id or executor.contract_version != binding.contract_version:
            raise CompilationError("executor metadata mismatch")


def validate_compiled_plan(plan, executors=None):
    if type(plan) is not CompiledExecutionPlan or plan.schema_version != PLAN_SCHEMA or plan.registry_version != "1.1.0":
        raise RuntimeContractError("unsupported compiled plan")
    if plan.scenario_key not in EXECUTABLE_SCENARIOS:
        raise CompilationError("scenario is not authorized for execution")
    if not re.fullmatch(r"[0-9a-f]{64}", plan.source_plan_id):
        raise RuntimeContractError("invalid plan identity")
    if type(plan.nodes) is not tuple or not 1 <= len(plan.nodes) <= 32 or type(plan.dependencies) is not tuple:
        raise RuntimeContractError("invalid bounded graph")
    registry = ModuleRegistry.load("1.1.0")
    ids = [n.node_id for n in plan.nodes]
    if len(set(ids)) != len(ids):
        raise RuntimeContractError("duplicate nodes")
    edges = [(e.upstream_node_id, e.downstream_node_id) for e in plan.dependencies]
    if len(set(edges)) != len(edges) or any(a not in ids or b not in ids for a, b in edges):
        raise RuntimeContractError("invalid edges")
    seen = set()
    for node in plan.nodes:
        validate_identity("validation", 1, node.node_id)
        refs = tuple(a for a, b in edges if b == node.node_id)
        if refs != node.dependency_node_ids or not set(refs) <= seen:
            raise RuntimeContractError("cycle, unordered graph or dependency mismatch")
        if not node.objective.strip():
            raise RuntimeContractError("empty objective")
        facts = (*node.context_packet.known_facts, *node.context_packet.relevant_project_context)
        if any(f.sensitivity is Sensitivity.SECRET or not f.authorized for f in facts):
            raise CompilationError("inline secret or unauthorized context is not persistable")
        if any(f.producer_node_id not in refs for f in node.context_packet.upstream_findings):
            raise CompilationError("unscoped upstream finding")
        _binding(node, registry, executors)
        seen.add(node.node_id)
    if plan.scenario_key == "competitive_positioning_v1" and (
        [(n.node_id, n.module_id) for n in plan.nodes] != [
            ("competitor_analysis", ModuleId.COMPETITOR_ANALYSIS), ("positioning", ModuleId.POSITIONING)
        ] or edges != [("competitor_analysis", "positioning")]
    ):
        raise CompilationError("invalid competitive-positioning topology")
    if plan.scenario_key == "explicit_single_module_v1" and (len(plan.nodes) != 1 or edges):
        raise CompilationError("invalid single-module topology")
    raw = bounded(plan)
    claimed = raw.pop("execution_fingerprint")
    if claimed != fingerprint(raw):
        raise RuntimeContractError("compiled plan fingerprint mismatch")


class PlanCompiler:
    def __init__(self, registry: ModuleRegistry, executors):
        self.registry, self.executors = registry, executors

    def compile(self, plan: OrchestrationPlan) -> CompiledExecutionPlan:
        try:
            return self._compile(plan)
        except (ValueError, LookupError, TypeError) as exc:
            raise CompilationError("plan is not eligible for execution") from exc

    def _compile(self, plan):
        if self.registry.version != "1.1.0":
            raise CompilationError("explicit Registry 1.1.0 required")
        if type(plan) is not OrchestrationPlan or (
            plan.planning_status is not PlanningStatus.VALIDATED
            or plan.structural_validity is not StructuralValidity.VALID
            or plan.blocking_questions or plan.stop_condition is not PlanningStopCondition.PLAN_COMPLETE
        ):
            raise CompilationError("source plan is not validated")
        if plan.scenario_key not in EXECUTABLE_SCENARIOS:
            raise CompilationError("scenario is not authorized for execution")
        baseline = ModuleRegistry.load("1.0.0")
        PlanValidator(baseline).validate(plan)
        nodes = []
        for node in plan.nodes:
            descriptor = self.registry.get(node.module_id)
            if replace(descriptor, availability_status=ModuleAvailabilityStatus.METADATA_ONLY,
                       execution_binding=None) != baseline.get(node.module_id):
                raise CompilationError("descriptor metadata mismatch")
            if node.quality_gate != descriptor.quality_gate:
                raise CompilationError("quality gate metadata mismatch")
            if any(not i.present and i.classification.value in {"REQUIRED", "BLOCKING"} for i in node.scoped_inputs):
                raise CompilationError("missing blocking input")
            compiled = CompiledExecutionNode(node.node_id, node.module_id, node.objective, node.expected_outputs,
                                             node.context_packet, node.dependency_references, descriptor.execution_binding)
            _binding(compiled, self.registry, self.executors)
            nodes.append(compiled)
        compiled = CompiledExecutionPlan(PLAN_SCHEMA, plan.plan_id, plan.scenario_key, self.registry.version,
                                         tuple(nodes), plan.dependencies, "")
        raw = bounded(compiled)
        raw.pop("execution_fingerprint")
        compiled = replace(compiled, execution_fingerprint=fingerprint(raw))
        validate_compiled_plan(compiled, self.executors)
        return compiled
