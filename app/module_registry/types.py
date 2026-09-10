from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping


class ModuleId(str, Enum):
    VIRTUAL_CMO = "VIRTUAL_CMO"
    BUSINESS_DIAGNOSTICS = "BUSINESS_DIAGNOSTICS"
    MARKET_ANALYSIS = "MARKET_ANALYSIS"
    COMPETITOR_ANALYSIS = "COMPETITOR_ANALYSIS"
    POSITIONING = "POSITIONING"
    AD_AUDIT = "AD_AUDIT"
    CJM = "CJM"
    CUSTDEV = "CUSTDEV"
    CREATOR = "CREATOR"
    COPY_EDITOR = "COPY_EDITOR"
    LEAD_MAGNET = "LEAD_MAGNET"
    TREND_MONITORING = "TREND_MONITORING"
    EXPERIMENTS = "EXPERIMENTS"
    PROJECT_DEFENSE = "PROJECT_DEFENSE"
    MENTOR = "MENTOR"


class ModuleType(str, Enum):
    PRIMARY = "PRIMARY"
    SUPPORTING = "SUPPORTING"
    OVERLAY = "OVERLAY"
    SYNTHESIS = "SYNTHESIS"


class InputRequirement(str, Enum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    OPTIONAL = "optional"
    BLOCKING_FOR_STRONG_CONCLUSION = "blocking_for_strong_conclusion"


class ToolCapability(str, Enum):
    WEB_ACCESS = "web_access"
    FILE_ANALYSIS = "file_analysis"
    SITE_FETCH = "site_fetch"
    IMAGE_GENERATION = "image_generation"
    CODE_GENERATION = "code_generation"


class ModuleAvailabilityStatus(str, Enum):
    METADATA_ONLY = "metadata_only"
    EXECUTION_BOUND = "execution_bound"


class ModuleResultStatus(str, Enum):
    PASS = "PASS"
    PASS_WITH_LIMITATIONS = "PASS_WITH_LIMITATIONS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({key: _deep_freeze(item) for key, item in value.items()})


def _deep_freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_deep_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ExecutionBinding:
    agent_id: str
    compatibility: str
    evidence: str


@dataclass(frozen=True, slots=True)
class ModuleDescriptor:
    module_id: ModuleId
    module_types: tuple[ModuleType, ...]
    purpose: str
    use_when: tuple[str, ...]
    do_not_use_when: tuple[str, ...]
    inputs: Mapping[InputRequirement, tuple[str, ...]]
    outputs: tuple[str, ...]
    supported_tools: frozenset[ToolCapability]
    quality_gate: tuple[str, ...]
    handoffs: tuple[ModuleId, ...]
    aliases: tuple[str, ...]
    authority_limitations: tuple[str, ...]
    availability_status: ModuleAvailabilityStatus
    execution_binding: ExecutionBinding | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "module_types", tuple(self.module_types))
        object.__setattr__(self, "use_when", tuple(self.use_when))
        object.__setattr__(self, "do_not_use_when", tuple(self.do_not_use_when))
        object.__setattr__(self, "inputs", MappingProxyType({key: tuple(value) for key, value in self.inputs.items()}))
        object.__setattr__(self, "outputs", tuple(self.outputs))
        object.__setattr__(self, "supported_tools", frozenset(self.supported_tools))
        object.__setattr__(self, "quality_gate", tuple(self.quality_gate))
        object.__setattr__(self, "handoffs", tuple(self.handoffs))
        object.__setattr__(self, "aliases", tuple(self.aliases))
        object.__setattr__(self, "authority_limitations", tuple(self.authority_limitations))


@dataclass(frozen=True, slots=True)
class ModuleActivation:
    module_id: ModuleId
    objective: str
    user_goal: str
    required_output: tuple[str, ...] = ()
    relevant_context: Mapping[str, Any] = field(default_factory=dict)
    known_facts: tuple[str, ...] = ()
    upstream_findings: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    confidence: str = ""
    constraints: tuple[str, ...] = ()
    available_tools: frozenset[ToolCapability] = frozenset()
    open_questions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "relevant_context", _freeze_mapping(self.relevant_context))
        for name in ("required_output", "known_facts", "upstream_findings", "evidence", "assumptions", "constraints", "open_questions"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "available_tools", frozenset(self.available_tools))


@dataclass(frozen=True, slots=True)
class ModuleResult:
    module_id: ModuleId
    status: ModuleResultStatus
    summary: str
    findings: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    hypotheses: tuple[str, ...] = ()
    recommendations: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    confidence: str = ""
    open_questions: tuple[str, ...] = ()
    strategic_issues: tuple[str, ...] = ()
    handoff_recommendation: tuple[ModuleId, ...] = ()

    def __post_init__(self) -> None:
        for name in ("findings", "evidence", "assumptions", "hypotheses", "recommendations", "risks", "open_questions", "strategic_issues", "handoff_recommendation"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
