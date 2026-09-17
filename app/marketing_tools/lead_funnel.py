"""Bounded decimal arithmetic. Rates are explicitly percentages, never fractions."""
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from enum import Enum
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictValue(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, revalidate_instances="always")


Quantity = Annotated[Decimal, Field(ge=0, le=Decimal("1e15"), allow_inf_nan=False)]
InputQuantity = Annotated[Decimal, Field(ge=0, le=Decimal("1e15"), allow_inf_nan=False, max_digits=28, decimal_places=12)]
UnitCost = Annotated[Decimal, Field(ge=Decimal("1e-12"), le=Decimal("1e15"), allow_inf_nan=False,
                                  max_digits=28, decimal_places=12)]


class FunnelTarget(str, Enum):
    LEADS = "leads"
    REQUIRED_TRAFFIC = "required_traffic"
    REQUIRED_BUDGET = "required_budget"


class FunnelInput(StrictValue):
    target: FunnelTarget = FunnelTarget.LEADS
    budget: InputQuantity | None = None
    cpc: UnitCost | None = None
    cpl: UnitCost | None = None
    traffic: InputQuantity | None = None
    conversion_rate_percent: Annotated[Decimal, Field(ge=0, le=100, allow_inf_nan=False, max_digits=15, decimal_places=12)] | None = None
    required_leads: InputQuantity | None = None


FORMULAS = {
    FunnelTarget.LEADS: (("budget", "cpl"), ("budget", "cpc", "conversion_rate_percent"),
                        ("traffic", "conversion_rate_percent")),
    FunnelTarget.REQUIRED_TRAFFIC: (("required_leads", "conversion_rate_percent"),),
    FunnelTarget.REQUIRED_BUDGET: (("required_leads", "cpl"),),
}


class ToolInputNeeded(ValueError):
    def __init__(self, target, code="missing_parameters"):
        super().__init__(code)
        self.code, self.alternatives = code, FORMULAS[target]


class FunnelOutput(StrictValue):
    formula: Literal["budget/cpl", "budget/cpc*rate", "traffic*rate", "required_leads/rate", "required_leads*cpl"]
    inputs: FunnelInput
    clicks: Quantity | None = None
    leads: Quantity | None = None
    required_traffic: Quantity | None = None
    required_budget: Quantity | None = None
    assumptions: tuple[str, ...] = (
        "All monetary inputs use the same caller-selected currency; no currency conversion or fees.",
        "Constant supplied unit costs and conversion rate; 34 significant decimal digits, fractional expected counts, no rounding to people.",
    )

    @model_validator(mode="after")
    def output_matches_target(self):
        present = (self.leads is not None, self.required_traffic is not None, self.required_budget is not None)
        if sum(present) != 1 or not present[list(FunnelTarget).index(self.inputs.target)]:
            raise ValueError("output must match requested target")
        return self


class LeadFunnelCalculator:
    key = "lead_funnel_calculator_v1"

    def execute(self, inputs: FunnelInput) -> FunnelOutput:
        inputs = FunnelInput.model_validate(inputs)
        supplied = {k for k, v in inputs.model_dump().items() if k != "target" and v is not None}
        # Require exactly one complete formula: extra values can be contradictory.
        formula = next((fields for fields in FORMULAS[inputs.target] if set(fields) == supplied), None)
        if formula is None:
            raise ToolInputNeeded(inputs.target, "missing_or_ambiguous_parameters")
        with localcontext(Context(prec=34, rounding=ROUND_HALF_EVEN)):
            rate = inputs.conversion_rate_percent / 100 if inputs.conversion_rate_percent is not None else None
            if inputs.target is FunnelTarget.REQUIRED_TRAFFIC:
                if rate == 0:
                    raise ToolInputNeeded(inputs.target, "positive_conversion_rate_required")
                return FunnelOutput(formula="required_leads/rate", inputs=inputs,
                                    required_traffic=inputs.required_leads / rate)
            if inputs.target is FunnelTarget.REQUIRED_BUDGET:
                return FunnelOutput(formula="required_leads*cpl", inputs=inputs,
                                    required_budget=inputs.required_leads * inputs.cpl)
            if inputs.cpl is not None:
                return FunnelOutput(formula="budget/cpl", inputs=inputs, leads=inputs.budget / inputs.cpl)
            if inputs.cpc is not None:
                clicks = inputs.budget / inputs.cpc
                return FunnelOutput(formula="budget/cpc*rate", inputs=inputs, clicks=clicks, leads=clicks * rate)
            return FunnelOutput(formula="traffic*rate", inputs=inputs, leads=inputs.traffic * rate)

    def parse(self, message: str) -> FunnelInput:
        """Small full-message grammar. Anything else needs explicit typed parameters.

        No partial regex extraction that might silently truncate ranges or units.
        """
        number = r"([0-9]+(?:[.,][0-9]+)?)"
        patterns = (
            (rf"рассчитай лиды при бюджете {number}, cpc {number} и конверсии {number}%", ("budget", "cpc", "conversion_rate_percent")),
            (rf"рассчитай лиды при бюджете {number} и cpl {number}", ("budget", "cpl")),
            (rf"рассчитай лиды при трафике {number} и конверсии {number}%", ("traffic", "conversion_rate_percent")),
        )
        for pattern, keys in patterns:
            match = re.fullmatch(pattern, message.strip(), re.IGNORECASE)
            if match:
                return FunnelInput(**{key: Decimal(value.replace(",", ".")) for key, value in zip(keys, match.groups())})
        raise ToolInputNeeded(FunnelTarget.LEADS, "explicit_parameters_required")
