from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from app.module_registry import ModuleId, ToolCapability


def deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): deep_freeze(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
        )
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(deep_freeze(item) for item in value)
    return value


class Sensitivity(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    SECRET = "SECRET"


class InputClassification(str, Enum):
    REQUIRED = "REQUIRED"
    BLOCKING = "BLOCKING"
    PREFERRED = "PREFERRED"
    OPTIONAL = "OPTIONAL"


class StructuralValidity(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"


class DataSufficiency(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


class PlanningStatus(str, Enum):
    VALIDATED = "VALIDATED"
    BLOCKED = "BLOCKED"
    UNSUPPORTED = "UNSUPPORTED"
    INVALID = "INVALID"


class ExecutionReadiness(str, Enum):
    PLANNING_ONLY = "PLANNING_ONLY"
    EXECUTABLE = "EXECUTABLE"


class PlanningStopCondition(str, Enum):
    PLAN_COMPLETE = "PLAN_COMPLETE"
    BLOCKING_INPUT_MISSING = "BLOCKING_INPUT_MISSING"
    UNKNOWN_MODULE = "UNKNOWN_MODULE"
    UNSUPPORTED_SCENARIO = "UNSUPPORTED_SCENARIO"
    INVALID_PLAN = "INVALID_PLAN"


@dataclass(frozen=True, slots=True)
class RequestInterpretation:
    requested_output: str
    decision_goal: str
    business_goal: str
    intent: str
    object: str
    depth: str
    mode: str
    constraints: tuple[str, ...] = ()
    requested_module: str | ModuleId | None = None
    scenario_key: str | None = None

    def __post_init__(self) -> None:
        for name in ("requested_output", "decision_goal", "business_goal", "intent", "object", "depth", "mode"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        object.__setattr__(self, "constraints", tuple(str(item).strip() for item in self.constraints if str(item).strip()))
        if (self.requested_module is None) == (self.scenario_key is None):
            raise ValueError("exactly one requested_module or scenario_key is required")
        if isinstance(self.requested_module, str):
            if not self.requested_module.strip():
                raise ValueError("requested_module must not be empty")
            object.__setattr__(self, "requested_module", self.requested_module.strip())
        if self.scenario_key is not None:
            if not self.scenario_key.strip():
                raise ValueError("scenario_key must not be empty")
            object.__setattr__(self, "scenario_key", self.scenario_key.strip())


@dataclass(frozen=True, slots=True)
class AuthorizedContextFact:
    key: str
    value: Any
    module_relevance: frozenset[ModuleId] = frozenset()
    scenario_relevance: frozenset[str] = frozenset()
    source: str = ""
    evidence: tuple[str, ...] = ()
    confidence: str = "UNKNOWN"
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    authorized: bool = True

    def __post_init__(self) -> None:
        key = self.key.strip() if isinstance(self.key, str) else ""
        if not key:
            raise ValueError("context fact key must be a non-empty string")
        object.__setattr__(self, "key", key)
        object.__setattr__(self, "value", deep_freeze(self.value))
        object.__setattr__(self, "module_relevance", frozenset(self.module_relevance))
        object.__setattr__(self, "scenario_relevance", frozenset(item.strip() for item in self.scenario_relevance if item.strip()))
        object.__setattr__(self, "evidence", tuple(item.strip() for item in self.evidence if item.strip()))


@dataclass(frozen=True, slots=True)
class UpstreamFinding:
    producer_node_id: str
    key: str
    value: Any
    evidence: tuple[str, ...] = ()
    confidence: str = "UNKNOWN"

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", deep_freeze(self.value))
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True, slots=True)
class PlanningContext:
    project_context: tuple[AuthorizedContextFact, ...] = ()
    known_facts: tuple[AuthorizedContextFact, ...] = ()
    upstream_findings: tuple[UpstreamFinding, ...] = ()
    assumptions: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    available_tools: frozenset[ToolCapability] = frozenset()

    def __post_init__(self) -> None:
        for name in ("project_context", "known_facts", "upstream_findings", "assumptions", "constraints"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "available_tools", frozenset(self.available_tools))


@dataclass(frozen=True, slots=True)
class ContextPacket:
    relevant_project_context: tuple[AuthorizedContextFact, ...] = ()
    known_facts: tuple[AuthorizedContextFact, ...] = ()
    upstream_findings: tuple[UpstreamFinding, ...] = ()
    evidence: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    confidence: str = "UNKNOWN"
    constraints: tuple[str, ...] = ()
    available_tools: frozenset[ToolCapability] = frozenset()
    open_questions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("relevant_project_context", "known_facts", "upstream_findings", "evidence", "assumptions", "constraints", "open_questions"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "available_tools", frozenset(self.available_tools))


@dataclass(frozen=True, slots=True)
class ScopedInput:
    key: str
    classification: InputClassification
    present: bool


@dataclass(frozen=True, slots=True)
class BlockingQuestion:
    input_key: str
    question: str
    node_id: str


@dataclass(frozen=True, slots=True)
class GraphDependency:
    upstream_node_id: str
    downstream_node_id: str


@dataclass(frozen=True, slots=True)
class PlanNode:
    node_id: str
    module_id: ModuleId
    objective: str
    scoped_inputs: tuple[ScopedInput, ...]
    expected_outputs: tuple[str, ...]
    quality_gate: tuple[str, ...]
    dependency_references: tuple[str, ...] = ()
    next_if_pass: str | None = None
    next_if_fail: str | None = None
    parallel_group: str | None = None
    parallelizable: bool = False
    context_packet: ContextPacket = field(default_factory=ContextPacket)

    def __post_init__(self) -> None:
        for name in ("scoped_inputs", "expected_outputs", "quality_gate", "dependency_references"):
            object.__setattr__(self, name, tuple(getattr(self, name)))


@dataclass(frozen=True, slots=True)
class OrchestrationPlan:
    plan_id: str
    scenario_key: str
    nodes: tuple[PlanNode, ...]
    dependencies: tuple[GraphDependency, ...]
    structural_validity: StructuralValidity
    data_sufficiency: DataSufficiency
    planning_status: PlanningStatus
    execution_readiness: ExecutionReadiness
    blocking_questions: tuple[BlockingQuestion, ...] = ()
    limitations: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    stop_condition: PlanningStopCondition = PlanningStopCondition.PLAN_COMPLETE

    def __post_init__(self) -> None:
        for name in ("nodes", "dependencies", "blocking_questions", "limitations", "assumptions"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
