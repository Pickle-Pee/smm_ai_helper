from decimal import Decimal
import pytest
from pydantic import ValidationError

from app.marketing_tools import FunnelInput, FunnelTarget, LeadFunnelCalculator, ToolInputNeeded


@pytest.mark.parametrize("target,inputs,field,expected", [
    (FunnelTarget.LEADS, {"budget": "100000", "cpc": "50", "conversion_rate_percent": "5"}, "leads", "100"),
    (FunnelTarget.LEADS, {"traffic": "2000", "conversion_rate_percent": "5"}, "leads", "100"),
    (FunnelTarget.LEADS, {"budget": "100000", "cpl": "1000"}, "leads", "100"),
    (FunnelTarget.REQUIRED_TRAFFIC, {"required_leads": "100", "conversion_rate_percent": "5"}, "required_traffic", "2000"),
    (FunnelTarget.REQUIRED_BUDGET, {"required_leads": "100", "cpl": "1000"}, "required_budget", "100000"),
    (FunnelTarget.LEADS, {"traffic": "10", "conversion_rate_percent": "0"}, "leads", "0"),
    (FunnelTarget.LEADS, {"traffic": "10", "conversion_rate_percent": "100"}, "leads", "10"),
])
def test_formulas(target, inputs, field, expected):
    output = LeadFunnelCalculator().execute(FunnelInput(target=target, **{k: Decimal(v) for k, v in inputs.items()}))
    assert getattr(output, field) == Decimal(expected)
    assert output.assumptions


@pytest.mark.parametrize("field,value", [
    ("budget", Decimal("-1")), ("budget", Decimal("1e16")), ("cpc", Decimal(0)),
    ("cpl", Decimal(0)), ("conversion_rate_percent", Decimal(101)),
    ("conversion_rate_percent", Decimal(-1)), ("traffic", Decimal("NaN")),
    ("traffic", Decimal("Infinity")), ("budget", True), ("budget", "100-200"),
    ("cpc", Decimal("1e-1000000")), ("conversion_rate_percent", Decimal("1e-1000000")),
])
def test_fail_closed_ranges(field, value):
    with pytest.raises(ValidationError):
        FunnelInput(**{field: value})


def test_zero_inverse_and_conflicting_formulas_and_missing():
    calculator = LeadFunnelCalculator()
    for inputs in (FunnelInput(), FunnelInput(target=FunnelTarget.REQUIRED_TRAFFIC,
                required_leads=Decimal(1), conversion_rate_percent=Decimal(0)),
                FunnelInput(budget=Decimal(10), cpl=Decimal(1), traffic=Decimal(20))):
        with pytest.raises(ToolInputNeeded):
            calculator.execute(inputs)


def test_arithmetic_is_independent_of_caller_decimal_context():
    from decimal import localcontext, ROUND_UP, Inexact
    inputs = FunnelInput(budget=Decimal(100), cpl=Decimal(3))
    expected = LeadFunnelCalculator().execute(inputs)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        assert LeadFunnelCalculator().execute(inputs) == expected


@pytest.mark.parametrize("message", [
    "Рассчитай лиды при бюджете 100-200 и CPL 10", "Рассчитай лиды при бюджете -100 и CPL 10",
    "Рассчитай лиды при бюджете 100 и CPL 10 долларов или 20 евро",
    "Рассчитай лиды при бюджете 100, CPC 10 и конверсии 5%-10%",
])
def test_parser_never_truncates_ranges_or_units(message):
    with pytest.raises(ToolInputNeeded):
        LeadFunnelCalculator().parse(message)
