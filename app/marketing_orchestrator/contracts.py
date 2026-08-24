from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias

from app.module_registry import ModuleId, ToolCapability


from .errors import InvalidContextValueError


ImmutableJsonScalar: TypeAlias = None | bool | int | float | str
ImmutableJsonValue: TypeAlias = ImmutableJsonScalar | tuple["ImmutableJsonValue", ...] | Mapping[str, "ImmutableJsonValue"]


def freeze_json_value(value: Any) -> ImmutableJsonValue:
    """Copy and freeze the supported deterministic JSON-like value domain."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise InvalidContextValueError("context floats must be finite")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise InvalidContextValueError("context mappings require string keys")
        return MappingProxyType(
            {key: freeze_json_value(item) for key, item in sorted(value.items())}
        )
    if isinstance(value, (list, tuple)):
        return tuple(freeze_json_value(item) for item in value)
    raise InvalidContextValueError(f"unsupported context value: {type(value).__name__}")


class Sensitivity(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    SECRET = "SECRET"


class InputClassification(str, Enum):
    REQUIRED = "REQUIRED"
    BLOCKING = "BLOCKING"
    PREFERRED = "PREFERRED"
    OPTIONAL = "OPTIONAL"


class PlanningInputKey(str, Enum):
    PRODUCT_OR_CATEGORY = "product_or_category"
    GEOGRAPHIC_SCOPE = "geographic_scope"
    BUSINESS_MODEL = "business_model"
    COMPETITOR_OR_CATEGORY_SCOPE = "competitor_or_category_scope"
    OBSERVABLE_EVIDENCE = "observable_evidence"
    TARGET_SEGMENT = "target_segment"
    PRODUCT = "product"
    TARGET_OR_TARGET_HYPOTHESIS = "target_or_target_hypothesis"
    CUSTOMER_JOB_OR_NEED = "customer_job_or_need"
    RELEVANT_ALTERNATIVE = "relevant_alternative"
    PRODUCT_TRUTH = "product_truth"
    EXISTING_PROOF = "existing_proof"


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
        object.__setattr__(
            self,
            "constraints",
            tuple(sorted({str(item).strip() for item in self.constraints if str(item).strip()})),
        )
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
    value: ImmutableJsonValue
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
        object.__setattr__(self, "value", freeze_json_value(self.value))
        object.__setattr__(self, "module_relevance", frozenset(self.module_relevance))
        object.__setattr__(self, "scenario_relevance", frozenset(item.strip() for item in self.scenario_relevance if item.strip()))
        object.__setattr__(self, "evidence", tuple(sorted({item.strip() for item in self.evidence if item.strip()})))


@dataclass(frozen=True, slots=True)
class UpstreamFinding:
    producer_node_id: str
    key: str
    value: ImmutableJsonValue
    evidence: tuple[str, ...] = ()
    confidence: str = "UNKNOWN"

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", freeze_json_value(self.value))
        object.__setattr__(self, "evidence", tuple(sorted(dict.fromkeys(self.evidence))))


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
class PlanningInputRequirement:
    key: PlanningInputKey
    classification: InputClassification
    priority: int
    module_id: ModuleId
    scenario_key: str
    question_template: str

    def __post_init__(self) -> None:
        if not isinstance(self.key, PlanningInputKey) or not isinstance(self.classification, InputClassification):
            raise ValueError("input requirement key and classification must be typed enums")
        if not isinstance(self.module_id, ModuleId):
            raise ValueError("input requirement module must be canonical")
        if self.priority < 0:
            raise ValueError("input requirement priority must be non-negative")
        if not self.scenario_key.strip() or not self.question_template.strip():
            raise ValueError("input requirement scenario and question template are required")


@dataclass(frozen=True, slots=True)
class ScopedInput:
    requirement: PlanningInputRequirement
    present: bool

    @property
    def key(self) -> str:
        return self.requirement.key.value

    @property
    def classification(self) -> InputClassification:
        return self.requirement.classification


@dataclass(frozen=True, slots=True)
class BlockingQuestion:
    input_key: PlanningInputKey
    question: str
    node_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.input_key, PlanningInputKey):
            raise ValueError("blocking question input key must be typed")
        if not self.question.strip() or not self.node_id.strip():
            raise ValueError("blocking question template and node are required")


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
