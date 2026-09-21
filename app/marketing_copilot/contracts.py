"""Strict semantic contracts. A routing proposal grants no execution authority."""
from enum import Enum
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.module_registry import ModuleId


class CopilotContractError(ValueError):
    """Invalid input at the non-executable copilot boundary."""


class ExecutionMode(str, Enum):
    CONVERSATION = "CONVERSATION"
    DIRECT_TOOL = "DIRECT_TOOL"
    SINGLE_MODULE = "SINGLE_MODULE"
    WORKFLOW = "WORKFLOW"


class IntentKind(str, Enum):
    CONVERSATION = "CONVERSATION"
    LEAD_FUNNEL_CALCULATION = "LEAD_FUNNEL_CALCULATION"
    POST_GENERATION = "POST_GENERATION"
    TEXT_EDITING = "TEXT_EDITING"
    COMPETITOR_ANALYSIS = "COMPETITOR_ANALYSIS"
    POSITIONING = "POSITIONING"
    COMPARATIVE_POSITIONING = "COMPARATIVE_POSITIONING"
    MARKETING_STRATEGY = "MARKETING_STRATEGY"
    UNSUPPORTED = "UNSUPPORTED"


class ReasonCode(str, Enum):
    CONVERSATION_REQUEST = "CONVERSATION_REQUEST"
    AMBIGUOUS_INTENT = "AMBIGUOUS_INTENT"
    UNSUPPORTED_INTENT = "UNSUPPORTED_INTENT"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    UNSUPPORTED_COMBINATION = "UNSUPPORTED_COMBINATION"
    DETERMINISTIC_CALCULATION = "DETERMINISTIC_CALCULATION"
    SINGLE_MODULE_REQUEST = "SINGLE_MODULE_REQUEST"
    POSITIONING_CONTEXT_SUFFICIENT = "POSITIONING_CONTEXT_SUFFICIENT"
    POSITIONING_CONTEXT_MISSING = "POSITIONING_CONTEXT_MISSING"
    COMPARATIVE_ANALYSES_REQUIRED = "COMPARATIVE_ANALYSES_REQUIRED"
    STRATEGY_WORKFLOW_REQUEST = "STRATEGY_WORKFLOW_REQUEST"
    EXTERNAL_EVIDENCE_REQUIRED = "EXTERNAL_EVIDENCE_REQUIRED"


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value  # Keep caller text; do not turn reference normalization into authority.


def _http_reference(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or any(char.isspace() or ord(char) < 32 for char in value)):
            raise ValueError
        parsed.port  # Reject malformed ports; this never resolves DNS or fetches a URL.
    except ValueError as exc:
        raise ValueError("must be an absolute HTTP(S) reference without credentials") from exc
    return value


Text = Annotated[str, StringConstraints(min_length=1, max_length=2000), AfterValidator(_nonblank)]
Reference = Annotated[str, StringConstraints(min_length=1, max_length=2048), AfterValidator(_nonblank)]
UrlReference = Annotated[Reference, AfterValidator(_http_reference)]


class _StrictContract(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always", hide_input_in_errors=True,
    )


class MarketingIntent(_StrictContract):
    """Model-supplied meaning, never an authorization, selector or executable binding."""

    kind: IntentKind
    requested_output: Text
    decision_goal: Text
    business_goal: Text | None = None
    subject: Text
    external_evidence_required: bool
    deterministic_calculation_required: bool
    provided_urls: tuple[UrlReference, ...] = Field(max_length=16)
    source_references: tuple[Reference, ...] = Field(max_length=16)
    constraints: tuple[Text, ...] = Field(max_length=16)
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    ambiguous: bool


ToolKey = Literal["lead_funnel_calculator_v1"]
ScenarioKey = Literal["new_positioning_v1", "competitive_positioning_v1", "strategy_builder_v1"]


class ExecutionDecision(_StrictContract):
    """Non-executable proposal. Selectors are data, not Python/Job/Registry bindings."""

    intent: MarketingIntent
    mode: ExecutionMode
    tool_key: ToolKey | None = None
    module_id: ModuleId | None = None
    scenario_key: ScenarioKey | None = None
    reason_codes: tuple[ReasonCode, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_selectors(self):
        present = (self.tool_key is not None, self.module_id is not None, self.scenario_key is not None)
        expected = {
            ExecutionMode.CONVERSATION: (False, False, False),
            ExecutionMode.DIRECT_TOOL: (True, False, False),
            ExecutionMode.SINGLE_MODULE: (False, True, False),
            ExecutionMode.WORKFLOW: (False, False, True),
        }
        if present != expected[self.mode]:
            raise ValueError("execution selectors do not match mode")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason_codes must be unique")
        return self
