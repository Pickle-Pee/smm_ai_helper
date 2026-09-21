"""Versioned public HTTP values. Internal execution envelopes never cross here."""
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Text = Annotated[str, StringConstraints(max_length=4000)]
Short = Annotated[str, StringConstraints(min_length=1, max_length=300)]
Url = Annotated[str, StringConstraints(min_length=1, max_length=2048)]
Identity = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")]


class StrictDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def safe_text(cls, value):
        def check(item, depth=0):
            if depth > 8:
                raise ValueError("Invalid nesting")
            if isinstance(item, str):
                if "\x00" in item:
                    raise ValueError("Invalid text")
                item.encode("utf-8")  # Reject unpaired surrogates before database/provider use.
            elif isinstance(item, dict):
                for key, child in item.items():
                    check(key, depth + 1)
                    check(child, depth + 1)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    check(child, depth + 1)
        check(value)
        return value


class BusinessContext(StrictDTO):
    business_goal: Text | None = None
    product: Text | None = None
    target: Text | None = None
    customer_job_or_need: Text | None = None
    relevant_alternative: Text | None = None
    product_truth: Text | None = None
    existing_proof: Text | None = None
    geography: Text | None = None
    economics: Text | None = None
    message: Text | None = None
    tone: Text | None = None


class MarketSource(StrictDTO):
    title: Short
    excerpt: Annotated[str, StringConstraints(min_length=1, max_length=8000)]


class Confirmation(StrictDTO):
    snapshot_id: Identity
    statement_ids: list[Identity] = Field(min_length=1, max_length=30)
    confirmed: Literal[True]
    reference: Short

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("Explicit confirmation required")
        return value

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.statement_ids)) != len(self.statement_ids):
            raise ValueError("Duplicate confirmation IDs")
        return self


class ExecuteRequest(StrictDTO):
    request_key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
    message: Annotated[str, StringConstraints(min_length=1, max_length=12000)]
    context: BusinessContext = Field(default_factory=BusinessContext)
    owned_site_url: Url | None = None
    competitor_urls: list[Url] = Field(default_factory=list, max_length=3)
    market_source_urls: list[Url] = Field(default_factory=list, max_length=3)
    market_sources: list[MarketSource] = Field(default_factory=list, max_length=8)
    confirmation: Confirmation | None = None

    @model_validator(mode="after")
    def bounded_request(self):
        if not self.message.strip():
            raise ValueError("Invalid request text")
        if self.confirmation is not None and self.owned_site_url is None:
            raise ValueError("Confirmation requires owned_site_url")
        if len(self.model_dump_json().encode()) > 131072:
            raise ValueError("Request exceeds context budget")
        return self


class ConfirmationCandidate(StrictDTO):
    statement_id: Identity
    field: Literal["stated_product_service", "stated_features_capabilities", "stated_value_propositions"]
    statement: Text
    source_url: Url
    trust: Literal["site_claim"] = "site_claim"


class OwnedSiteResult(StrictDTO):
    outcome: Literal["ACQUIRED", "UNSAFE_SOURCE", "SOURCE_UNAVAILABLE", "EMPTY_CONTENT",
                     "CAPABILITY_UNAVAILABLE", "INVALID_EXTRACTION"]
    snapshot_id: Identity | None = None
    candidates: list[ConfirmationCandidate] = Field(default_factory=list, max_length=30)


class Finding(StrictDTO):
    topic: Short
    text: Text
    kind: Literal["OBSERVATION", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION"]
    confidence: Literal["UNKNOWN", "LOW", "MEDIUM", "HIGH"]


class SourceSummary(StrictDTO):
    label: Short
    url: Url | None = None


class Findings(StrictDTO):
    kind: Literal["competitor_analysis", "market_analysis", "positioning"]
    findings: list[Finding] = Field(max_length=32)
    sources: list[SourceSummary] = Field(default_factory=list, max_length=64)
    limitations: list[Text] = Field(default_factory=list, max_length=64)


class Post(StrictDTO):
    kind: Literal["post"] = "post"
    headline: Text
    body: Text
    cta: Text
    limitations: list[Text] = Field(default_factory=list, max_length=64)


class StrategySection(StrictDTO):
    text: Text
    items: list[Short] = Field(min_length=1, max_length=3)


class Strategy(StrictDTO):
    strategic_diagnosis: StrategySection
    main_growth_constraint: StrategySection
    strategic_priorities: StrategySection
    trade_offs: StrategySection
    resource_priorities: StrategySection
    strategic_bets: StrategySection
    roadmap: StrategySection
    risks: StrategySection
    decision_triggers: StrategySection
    limitations: list[Text] = Field(default_factory=list, max_length=64)


class Experiment(StrictDTO):
    hypothesis: Short
    target_metric: Short
    intervention: Short
    expected_signal: Short
    failure_condition: Short
    minimum_required_inputs: list[Short] = Field(max_length=5)
    time_resource_constraints: list[Short] = Field(max_length=8)


class Experiments(StrictDTO):
    designs: list[Experiment] = Field(max_length=3)
    limitations: list[Text] = Field(default_factory=list, max_length=64)


class CalculationInputs(StrictDTO):
    budget: Short | None = None
    cpc: Short | None = None
    cpl: Short | None = None
    traffic: Short | None = None
    conversion_rate_percent: Short | None = None
    required_leads: Short | None = None


class CalculationOutputs(StrictDTO):
    clicks: Short | None = None
    leads: Short | None = None
    required_traffic: Short | None = None
    required_budget: Short | None = None


class Calculation(StrictDTO):
    calculation_type: Literal["leads", "required_traffic", "required_budget"]
    formula: Literal["budget/cpl", "budget/cpc*rate", "traffic*rate", "required_leads/rate", "required_leads*cpl"]
    inputs: CalculationInputs
    outputs: CalculationOutputs
    assumptions: list[Text] = Field(max_length=8)


class ResponseBase(StrictDTO):
    schema_version: Literal["copilot_api.v1"] = "copilot_api.v1"
    owned_site: OwnedSiteResult | None = None


class ConversationResponse(ResponseBase):
    kind: Literal["CONVERSATION"] = "CONVERSATION"
    delegate: Literal["legacy_chat"] = "legacy_chat"


class DirectResponse(ResponseBase):
    kind: Literal["DIRECT_RESULT"] = "DIRECT_RESULT"
    calculation: Calculation


class ModuleResponse(ResponseBase):
    kind: Literal["MODULE_RESULT"] = "MODULE_RESULT"
    result: Post | Findings


class NeedsInputResponse(ResponseBase):
    kind: Literal["NEEDS_INPUT"] = "NEEDS_INPUT"
    code: Short
    alternatives: list[list[Short]] = Field(min_length=1, max_length=32)
    actions: list[Short] = Field(default_factory=list, max_length=8)


class StartedResponse(ResponseBase):
    kind: Literal["WORKFLOW_STARTED"] = "WORKFLOW_STARTED"
    run_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    status: Literal["ACCEPTED"] = "ACCEPTED"
    status_url: Short


ExecuteResponse = Annotated[ConversationResponse | DirectResponse | ModuleResponse | NeedsInputResponse | StartedResponse,
                            Field(discriminator="kind")]


class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_LIMITATIONS = "COMPLETED_WITH_LIMITATIONS"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class Coverage(StrictDTO):
    competitors_supplied: int = Field(ge=0, le=3)
    competitors_accepted: int = Field(ge=0, le=3)
    limitations: list[Text] = Field(default_factory=list, max_length=32)


class RunSummary(StrictDTO):
    run_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    status: RunStatus
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def timestamp(cls, value):
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError("Expected an ISO timestamp with timezone")
        return value


class RunListResponse(StrictDTO):
    schema_version: Literal["copilot_api.v1"] = "copilot_api.v1"
    items: list[RunSummary] = Field(max_length=50)
    next_offset: int | None = Field(default=None, ge=0, le=10000)


class PublicFailure(StrictDTO):
    code: Literal["context_required", "result_unavailable"]
    message: Short
    actions: list[Short] = Field(max_length=8)


class RunResponse(StrictDTO):
    schema_version: Literal["copilot_api.v1"] = "copilot_api.v1"
    run_id: str
    status: RunStatus
    strategy: Strategy | None = None
    experiments: Experiments | None = None
    details: list[Findings] = Field(default_factory=list, max_length=5)
    evidence_coverage: Coverage | None = None
    limitations: list[Text] = Field(default_factory=list, max_length=64)
    failure: PublicFailure | None = None


class ErrorResponse(ResponseBase):
    kind: Literal["ERROR"] = "ERROR"
    code: Literal["request_conflict", "confirmation_changed", "invalid_confirmation", "temporarily_unavailable",
                  "not_found", "invalid_request"]
