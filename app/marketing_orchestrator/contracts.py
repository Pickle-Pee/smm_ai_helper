from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, TypeAlias

from app.module_registry import ModuleId, ToolCapability


from .errors import InvalidContextValueError


ImmutableJsonScalar: TypeAlias = None | bool | int | float | str
ImmutableJsonValue: TypeAlias = ImmutableJsonScalar | tuple["ImmutableJsonValue", ...] | Mapping[str, "ImmutableJsonValue"]
_STABLE_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._:-][a-z0-9]+)*$")


def _error(field: str, message: str) -> InvalidContextValueError:
    return InvalidContextValueError(f"{field}: {message}")


def _string(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or not value.strip():
        raise _error(field, "must be a non-empty string")
    return value.strip()


def _identifier(value: Any, field: str) -> str:
    result = _string(value, field)
    assert isinstance(result, str)
    if len(result) > 128 or _STABLE_ID.fullmatch(result) is None:
        raise _error(field, "must use the stable lowercase identifier format")
    return result


def _strings(value: Any, field: str, *, ordered: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise _error(field, "must be a tuple or list of strings")
    items = tuple(_string(item, f"{field} item") for item in value)
    return items if ordered else tuple(sorted(set(items)))  # type: ignore[arg-type]


def _typed_sequence(value: Any, item_type: type, field: str) -> tuple[Any, ...]:
    if not isinstance(value, (tuple, list)):
        raise _error(field, "must be a tuple or list")
    if any(type(item) is not item_type for item in value):
        raise _error(field, f"items must be {item_type.__name__}")
    return tuple(value)


def _enum_set(value: Any, item_type: type[Enum], field: str) -> frozenset[Any]:
    if not isinstance(value, (set, frozenset, tuple, list)):
        raise _error(field, "must be an explicit enum collection")
    if any(type(item) is not item_type for item in value):
        raise _error(field, f"items must be {item_type.__name__}")
    return frozenset(value)


def _string_set(value: Any, field: str) -> frozenset[str]:
    if not isinstance(value, (set, frozenset, tuple, list)):
        raise _error(field, "must be an explicit string collection")
    return frozenset(_strings(tuple(value), field))


def _confidence(value: Any, field: str) -> float:
    if type(value) is not float or not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise _error(field, "must be a finite float from 0.0 through 1.0")
    return value


def freeze_json_value(value: Any) -> ImmutableJsonValue:
    """Copy and freeze the supported deterministic JSON-like value domain."""
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
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
            if type(value) is not str or not value.strip():
                raise _error(name, "must be a non-empty string")
            object.__setattr__(self, name, value.strip())
        object.__setattr__(
            self,
            "constraints",
            _strings(self.constraints, "constraints"),
        )
        if (self.requested_module is None) == (self.scenario_key is None):
            raise _error("selector", "exactly one requested_module or scenario_key is required")
        if self.requested_module is not None and type(self.requested_module) not in (str, ModuleId):
            raise _error("requested_module", "must be a string or ModuleId")
        if isinstance(self.requested_module, str):
            if not self.requested_module.strip():
                raise _error("requested_module", "must not be empty")
            object.__setattr__(self, "requested_module", self.requested_module.strip())
        if self.scenario_key is not None:
            if type(self.scenario_key) is not str or not self.scenario_key.strip():
                raise _error("scenario_key", "must not be empty")
            object.__setattr__(self, "scenario_key", self.scenario_key.strip())


@dataclass(frozen=True, slots=True)
class AuthorizedContextFact:
    fact_id: str
    label: str
    value: ImmutableJsonValue
    input_key: PlanningInputKey | None = None
    module_relevance: frozenset[ModuleId] = frozenset()
    scenario_relevance: frozenset[str] = frozenset()
    source: str = ""
    evidence: tuple[str, ...] = ()
    confidence: float = 0.0
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    authorized: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "fact_id", _identifier(self.fact_id, "fact_id"))
        object.__setattr__(self, "label", _string(self.label, "label"))
        if self.input_key is not None and type(self.input_key) is not PlanningInputKey:
            raise _error("input_key", "must be PlanningInputKey or None")
        object.__setattr__(self, "value", freeze_json_value(self.value))
        object.__setattr__(self, "module_relevance", _enum_set(self.module_relevance, ModuleId, "module_relevance"))
        object.__setattr__(self, "scenario_relevance", _string_set(self.scenario_relevance, "scenario_relevance"))
        object.__setattr__(self, "source", _string(self.source, "source"))
        object.__setattr__(self, "evidence", _strings(self.evidence, "evidence"))
        object.__setattr__(self, "confidence", _confidence(self.confidence, "confidence"))
        if type(self.sensitivity) is not Sensitivity:
            raise _error("sensitivity", "must be Sensitivity")
        if type(self.authorized) is not bool:
            raise _error("authorized", "must be bool")


@dataclass(frozen=True, slots=True)
class UpstreamFinding:
    producer_node_id: str
    key: str
    value: ImmutableJsonValue
    evidence: tuple[str, ...] = ()
    confidence: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "producer_node_id", _identifier(self.producer_node_id, "producer_node_id"))
        object.__setattr__(self, "key", _identifier(self.key, "key"))
        object.__setattr__(self, "value", freeze_json_value(self.value))
        object.__setattr__(self, "evidence", _strings(self.evidence, "evidence"))
        object.__setattr__(self, "confidence", _confidence(self.confidence, "confidence"))


@dataclass(frozen=True, slots=True)
class PlanningContext:
    project_context: tuple[AuthorizedContextFact, ...] = ()
    known_facts: tuple[AuthorizedContextFact, ...] = ()
    upstream_findings: tuple[UpstreamFinding, ...] = ()
    assumptions: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    available_tools: frozenset[ToolCapability] = frozenset()

    def __post_init__(self) -> None:
        project = _typed_sequence(self.project_context, AuthorizedContextFact, "project_context")
        known = _typed_sequence(self.known_facts, AuthorizedContextFact, "known_facts")
        upstream = _typed_sequence(self.upstream_findings, UpstreamFinding, "upstream_findings")
        ids = [item.fact_id for item in (*project, *known)]
        if len(ids) != len(set(ids)):
            raise _error("fact_id", "must be unique within PlanningContext")
        object.__setattr__(self, "project_context", project)
        object.__setattr__(self, "known_facts", known)
        object.__setattr__(self, "upstream_findings", upstream)
        object.__setattr__(self, "assumptions", _strings(self.assumptions, "assumptions"))
        object.__setattr__(self, "constraints", _strings(self.constraints, "constraints"))
        object.__setattr__(self, "available_tools", _enum_set(self.available_tools, ToolCapability, "available_tools"))


@dataclass(frozen=True, slots=True)
class ContextPacket:
    relevant_project_context: tuple[AuthorizedContextFact, ...] = ()
    known_facts: tuple[AuthorizedContextFact, ...] = ()
    upstream_findings: tuple[UpstreamFinding, ...] = ()
    evidence: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    confidence: float = 0.0
    constraints: tuple[str, ...] = ()
    available_tools: frozenset[ToolCapability] = frozenset()
    open_questions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name, kind in (("relevant_project_context", AuthorizedContextFact), ("known_facts", AuthorizedContextFact), ("upstream_findings", UpstreamFinding)):
            object.__setattr__(self, name, _typed_sequence(getattr(self, name), kind, name))
        ids = [item.fact_id for item in (*self.relevant_project_context, *self.known_facts)]
        if len(ids) != len(set(ids)):
            raise _error("fact_id", "must be unique within ContextPacket")
        for name in ("evidence", "assumptions", "constraints", "open_questions"):
            object.__setattr__(self, name, _strings(getattr(self, name), name))
        object.__setattr__(self, "confidence", _confidence(self.confidence, "confidence"))
        object.__setattr__(self, "available_tools", _enum_set(self.available_tools, ToolCapability, "available_tools"))


@dataclass(frozen=True, slots=True)
class PlanningInputRequirement:
    key: PlanningInputKey
    classification: InputClassification
    priority: int
    module_id: ModuleId
    scenario_key: str
    question_template: str

    def __post_init__(self) -> None:
        if type(self.key) is not PlanningInputKey or type(self.classification) is not InputClassification:
            raise _error("input requirement", "key and classification must be typed enums")
        if type(self.module_id) is not ModuleId:
            raise _error("module_id", "must be canonical ModuleId")
        if type(self.priority) is not int or self.priority < 0:
            raise _error("priority", "must be a non-negative integer")
        object.__setattr__(self, "scenario_key", _identifier(self.scenario_key, "scenario_key"))
        object.__setattr__(self, "question_template", _string(self.question_template, "question_template"))


@dataclass(frozen=True, slots=True)
class ScopedInput:
    requirement: PlanningInputRequirement
    present: bool

    def __post_init__(self) -> None:
        if type(self.requirement) is not PlanningInputRequirement:
            raise _error("requirement", "must be PlanningInputRequirement")
        if type(self.present) is not bool:
            raise _error("present", "must be bool")

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
        if type(self.input_key) is not PlanningInputKey:
            raise _error("input_key", "must be PlanningInputKey")
        object.__setattr__(self, "question", _string(self.question, "question"))
        object.__setattr__(self, "node_id", _identifier(self.node_id, "node_id"))


@dataclass(frozen=True, slots=True)
class GraphDependency:
    upstream_node_id: str
    downstream_node_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "upstream_node_id", _identifier(self.upstream_node_id, "upstream_node_id"))
        object.__setattr__(self, "downstream_node_id", _identifier(self.downstream_node_id, "downstream_node_id"))


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
        object.__setattr__(self, "node_id", _identifier(self.node_id, "node_id"))
        if type(self.module_id) is not ModuleId:
            raise _error("module_id", "must be ModuleId")
        object.__setattr__(self, "objective", _string(self.objective, "objective"))
        object.__setattr__(self, "scoped_inputs", _typed_sequence(self.scoped_inputs, ScopedInput, "scoped_inputs"))
        for name in ("expected_outputs", "quality_gate", "dependency_references"):
            object.__setattr__(self, name, _strings(getattr(self, name), name, ordered=True))
        for name in ("next_if_pass", "next_if_fail", "parallel_group"):
            object.__setattr__(self, name, _string(getattr(self, name), name, optional=True))
        if type(self.parallelizable) is not bool:
            raise _error("parallelizable", "must be bool")
        if type(self.context_packet) is not ContextPacket:
            raise _error("context_packet", "must be ContextPacket")


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
        if type(self.plan_id) is not str or len(self.plan_id) != 64 or any(item not in "0123456789abcdef" for item in self.plan_id):
            raise _error("plan_id", "must be a lowercase SHA-256 identifier")
        object.__setattr__(self, "scenario_key", _identifier(self.scenario_key, "scenario_key"))
        for name, kind in (("nodes", PlanNode), ("dependencies", GraphDependency), ("blocking_questions", BlockingQuestion)):
            object.__setattr__(self, name, _typed_sequence(getattr(self, name), kind, name))
        for name in ("limitations", "assumptions"):
            object.__setattr__(self, name, _strings(getattr(self, name), name, ordered=True))
        for name, kind in (
            ("structural_validity", StructuralValidity), ("data_sufficiency", DataSufficiency),
            ("planning_status", PlanningStatus), ("execution_readiness", ExecutionReadiness),
            ("stop_condition", PlanningStopCondition),
        ):
            if type(getattr(self, name)) is not kind:
                raise _error(name, f"must be {kind.__name__}")
