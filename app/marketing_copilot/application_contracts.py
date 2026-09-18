"""Internal caller-owned values; no transport objects or persistence entities."""
from dataclasses import dataclass
from enum import Enum

from app.marketing_orchestrator import UpstreamFinding
from app.marketing_tools import FunnelInput, FunnelOutput
from app.module_execution import ModuleExecutionResult
from app.module_registry import ToolCapability
from .context_resolver import ContextEntry
from .contracts import CopilotContractError, ExecutionDecision, ExecutionMode


def text(value, limit=2000):
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise CopilotContractError("Expected bounded nonempty text")


def records(values, cls, limit=128):
    if type(values) is not tuple or len(values) > limit or any(type(v) is not cls for v in values):
        raise CopilotContractError("Expected bounded immutable typed records")


@dataclass(frozen=True, slots=True, kw_only=True)
class CopilotRequest:
    """Caller must authorize actor, context, tools and each supplied artifact reference."""
    actor_id: int
    request_id: str
    message: str
    current_request: tuple[ContextEntry, ...] = ()
    project_run: tuple[ContextEntry, ...] = ()
    brand_profile: tuple[ContextEntry, ...] = ()
    conversation: tuple[ContextEntry, ...] = ()
    authorized_upstream_findings: tuple[UpstreamFinding, ...] = ()
    available_tools: frozenset[ToolCapability] = frozenset()
    assumptions: tuple[str, ...] = ()
    constraints: tuple[str, ...] = ()
    project_id: str | None = None
    current_run_id: str | None = None
    calculation: FunnelInput | None = None
    owned_site_url: str | None = None
    owned_site_context: tuple[ContextEntry, ...] = ()

    def __post_init__(self):
        if type(self.actor_id) is not int or self.actor_id <= 0:
            raise CopilotContractError("Positive internal actor identity required")
        text(self.request_id, 128)
        text(self.message, 12000)
        for name in ("current_request", "owned_site_context", "project_run", "brand_profile", "conversation"):
            records(getattr(self, name), ContextEntry)
        if self.owned_site_url is not None:
            text(self.owned_site_url, 2048)
        elif self.owned_site_context:
            raise CopilotContractError("Owned-site context requires an explicitly declared owned_site_url")
        records(self.authorized_upstream_findings, UpstreamFinding)
        if type(self.available_tools) is not frozenset or any(type(t) is not ToolCapability for t in self.available_tools):
            raise CopilotContractError("Explicit tool capabilities required")
        for values in (self.assumptions, self.constraints):
            records(values, str, 32)
            for value in values:
                text(value)
        for value in (self.project_id, self.current_run_id):
            if value is not None:
                text(value, 128)
        if self.calculation is not None:
            if type(self.calculation) is not FunnelInput:
                raise CopilotContractError("Expected typed calculation input")
            FunnelInput.model_validate(self.calculation)


class ResultKind(str, Enum):
    CONVERSATION = "CONVERSATION"
    DIRECT_RESULT = "DIRECT_RESULT"
    MODULE_RESULT = "MODULE_RESULT"
    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    NEEDS_INPUT = "NEEDS_INPUT"


@dataclass(frozen=True, slots=True)
class Clarification:
    code: str
    alternatives: tuple[tuple[str, ...], ...]
    blocking_reasons: tuple[str, ...] = ()

    def __post_init__(self):
        text(self.code, 128)
        records(self.alternatives, tuple, 32)
        if not self.alternatives:
            raise CopilotContractError("Grouped clarification must have alternatives")
        for group in self.alternatives:
            records(group, str, 32)
            if not group:
                raise CopilotContractError("Clarification group must not be empty")
            for key in group:
                text(key)
        records(self.blocking_reasons, str, 32)
        for reason in self.blocking_reasons:
            text(reason)


@dataclass(frozen=True, slots=True)
class WorkflowStarted:
    run_id: str
    plan_id: str
    status: str = "durably_started"

    def __post_init__(self):
        text(self.run_id, 128)
        text(self.plan_id, 128)
        # A start acknowledgement is not a possibly stale queue/completion status.
        if self.status != "durably_started":
            raise CopilotContractError("Invalid workflow acknowledgement")


@dataclass(frozen=True, slots=True, kw_only=True)
class CopilotExecutionResult:
    request_id: str
    execution_id: str
    decision: ExecutionDecision
    kind: ResultKind
    direct_result: FunnelOutput | None = None
    module_result: ModuleExecutionResult | None = None
    workflow: WorkflowStarted | None = None
    clarification: Clarification | None = None
    conversation_delegate: bool = False

    def __post_init__(self):
        text(self.request_id, 128)
        text(self.execution_id, 128)
        if type(self.decision) is not ExecutionDecision or type(self.kind) is not ResultKind:
            raise CopilotContractError("Typed decision and result kind required")
        ExecutionDecision.model_validate(self.decision)
        fields = (self.direct_result, self.module_result, self.workflow, self.clarification)
        types = (FunnelOutput, ModuleExecutionResult, WorkflowStarted, Clarification)
        for value, cls in zip(fields, types):
            if value is not None and type(value) is not cls:
                raise CopilotContractError("Incorrect result payload type")
        expected = {
            ResultKind.DIRECT_RESULT: 0, ResultKind.MODULE_RESULT: 1,
            ResultKind.WORKFLOW_STARTED: 2, ResultKind.NEEDS_INPUT: 3,
        }
        if self.kind is ResultKind.CONVERSATION:
            valid = all(v is None for v in fields) and self.conversation_delegate is True
        else:
            valid = self.conversation_delegate is False and all(
                (v is not None) == (i == expected[self.kind]) for i, v in enumerate(fields))
        if not valid:
            raise CopilotContractError("Result kind and payload disagree")
        mode = {
            ResultKind.CONVERSATION: ExecutionMode.CONVERSATION,
            ResultKind.DIRECT_RESULT: ExecutionMode.DIRECT_TOOL,
            ResultKind.MODULE_RESULT: ExecutionMode.SINGLE_MODULE,
            ResultKind.WORKFLOW_STARTED: ExecutionMode.WORKFLOW,
        }.get(self.kind)
        if mode is not None and self.decision.mode is not mode:
            raise CopilotContractError("Result kind and decision mode disagree")
