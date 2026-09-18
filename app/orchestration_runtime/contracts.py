"""Immutable execution description, separate from planning and database state."""
from dataclasses import dataclass
import hashlib
import re
from enum import Enum

from app.marketing_orchestrator.contracts import ContextPacket, GraphDependency
from app.module_registry import ExecutionBinding, ModuleId
from .errors import RuntimeContractError

WORKFLOW_TYPE = "orchestration_graph.v1"
JOB_KIND = "orchestration.module"
PLAN_SCHEMA = "compiled_execution_plan.v1"
PLAN_SCHEMA_V2 = "compiled_execution_plan.v2"
ARTIFACT_SCHEMA = "module_artifact.v1"
# Execution permission is owned by the runtime, independently of planning support.
EXECUTABLE_SCENARIOS = frozenset({"explicit_single_module_v1", "competitive_positioning_v1", "strategy_builder_v1"})


@dataclass(frozen=True, slots=True)
class CompiledExecutionNode:
    node_id: str
    module_id: ModuleId
    objective: str
    expected_outputs: tuple[str, ...]
    context_packet: ContextPacket
    dependency_node_ids: tuple[str, ...]
    binding: ExecutionBinding

    def __post_init__(self):
        validate_identity("validation", 1, self.node_id)
        if (type(self.module_id) is not ModuleId or type(self.context_packet) is not ContextPacket
                or type(self.binding) is not ExecutionBinding or type(self.objective) is not str
                or not self.objective.strip()):
            raise RuntimeContractError("invalid compiled node")
        for values in (self.expected_outputs, self.dependency_node_ids):
            if type(values) is not tuple or any(type(v) is not str for v in values):
                raise RuntimeContractError("compiled node collections must be immutable")


@dataclass(frozen=True, slots=True)
class CompiledExecutionPlan:
    schema_version: str
    source_plan_id: str
    scenario_key: str
    registry_version: str
    nodes: tuple[CompiledExecutionNode, ...]
    dependencies: tuple[GraphDependency, ...]
    execution_fingerprint: str

    def __post_init__(self):
        if type(self.nodes) is not tuple or any(type(n) is not CompiledExecutionNode for n in self.nodes):
            raise RuntimeContractError("compiled nodes must be immutable")
        if type(self.dependencies) is not tuple or any(type(e) is not GraphDependency for e in self.dependencies):
            raise RuntimeContractError("compiled dependencies must be immutable")
        if any(type(v) is not str for v in (self.schema_version, self.source_plan_id, self.scenario_key,
                                          self.registry_version, self.execution_fingerprint)):
            raise RuntimeContractError("invalid compiled plan metadata")


@dataclass(frozen=True, slots=True)
class GraphWorkItem:
    job_id: str
    run_id: str
    plan_revision: int
    node_id: str
    claim_token: str


class NodeFailureMode(str, Enum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"


class DependencyMode(str, Enum):
    HARD = "HARD"
    OPTIONAL_CONTRIBUTOR = "OPTIONAL_CONTRIBUTOR"


@dataclass(frozen=True, slots=True)
class CompiledExecutionNodeV2(CompiledExecutionNode):
    failure_mode: NodeFailureMode

    def __post_init__(self):
        CompiledExecutionNode.__post_init__(self)
        if type(self.failure_mode) is not NodeFailureMode:
            raise RuntimeContractError("invalid failure mode")


@dataclass(frozen=True, slots=True)
class CompiledDependency:
    upstream_node_id: str
    downstream_node_id: str
    mode: DependencyMode

    def __post_init__(self):
        validate_identity("validation", 1, self.upstream_node_id)
        validate_identity("validation", 1, self.downstream_node_id)
        if type(self.mode) is not DependencyMode:
            raise RuntimeContractError("invalid dependency mode")


@dataclass(frozen=True, slots=True)
class CompiledExecutionPlanV2:
    schema_version: str
    source_plan_id: str
    scenario_key: str
    registry_version: str
    nodes: tuple[CompiledExecutionNodeV2, ...]
    dependencies: tuple[CompiledDependency, ...]
    execution_fingerprint: str
    limitations: tuple[str, ...]

    def __post_init__(self):
        if type(self.nodes) is not tuple or any(type(n) is not CompiledExecutionNodeV2 for n in self.nodes):
            raise RuntimeContractError("invalid v2 nodes")
        if type(self.dependencies) is not tuple or any(type(e) is not CompiledDependency for e in self.dependencies):
            raise RuntimeContractError("invalid v2 dependencies")
        if (type(self.limitations) is not tuple or len(self.limitations) > 32
                or any(type(v) is not str or not 1 <= len(v) <= 256 for v in self.limitations)):
            raise RuntimeContractError("invalid bounded planning limitations")
        if any(type(v) is not str for v in (self.schema_version, self.source_plan_id, self.scenario_key,
                                          self.registry_version, self.execution_fingerprint)):
            raise RuntimeContractError("invalid v2 metadata")


def optional(node):
    return isinstance(node, CompiledExecutionNodeV2) and node.failure_mode is NodeFailureMode.OPTIONAL


def hard_predecessors(plan, node):
    return tuple(e.upstream_node_id for e in plan.dependencies if e.downstream_node_id == node.node_id
                 and (type(e) is GraphDependency or e.mode is DependencyMode.HARD))


def validate_identity(run_id, revision, node_id):
    if type(run_id) is not str or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", run_id):
        raise RuntimeContractError("invalid run identity")
    if type(revision) is not int or not 1 <= revision <= 2_147_483_647:
        raise RuntimeContractError("invalid revision")
    if type(node_id) is not str or not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", node_id):
        raise RuntimeContractError("node ID is incompatible with workflow_step")


def artifact_key(run_id: str, revision: int, node_id: str) -> str:
    # run_id is the other column of the artifact unique identity, not discarded.
    validate_identity(run_id, revision, node_id)
    return f"p{revision}.{node_id}"


def module_job_id(run_id: str, revision: int, node_id: str) -> str:
    validate_identity(run_id, revision, node_id)
    return hashlib.sha256(f"{WORKFLOW_TYPE}:{run_id}:{revision}:{node_id}".encode()).hexdigest()[:32]
