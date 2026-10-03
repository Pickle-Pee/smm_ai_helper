from decimal import Decimal
import pytest
from pydantic import ValidationError

from app.marketing_tools import FunnelInput, FunnelTarget, LeadFunnelCalculator, ToolInputNeeded


def test_issue_70_natural_russian_ruble_request():
    calculator = LeadFunnelCalculator()
    expected = FunnelInput(budget=Decimal("10000"), cpl=Decimal("500"))
    canonical = calculator.parse("Рассчитай лиды при бюджете 10000 и CPL 500")
    assert canonical == expected
    assert calculator.execute(expected).leads == Decimal("20")

    parsed = calculator.parse("Рассчитай количество лидов при бюджете 10000 ₽ и CPL 500 ₽")
    assert parsed == expected
    assert calculator.execute(parsed).leads == Decimal("20")


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


@pytest.mark.parametrize("wording", ["лиды", "количество лидов", "сколько лидов"])
@pytest.mark.parametrize("marker", ["", "₽", "руб", "руб.", "рублей", "РУБ."])
@pytest.mark.parametrize("spacing", ["", " ", "   "])
def test_parser_lead_wording_and_monetary_markers(wording, marker, spacing):
    parsed = LeadFunnelCalculator().parse(
        f"Рассчитай {wording} при бюджете 10 000{spacing}{marker} и Cpl 500{spacing}{marker}"
    )
    assert parsed == FunnelInput(budget=Decimal("10000"), cpl=Decimal("500"))
    assert LeadFunnelCalculator().execute(parsed).leads == Decimal("20")


@pytest.mark.parametrize("token,expected", [
    ("10000", "10000"), ("10000.50", "10000.50"), ("10000,50", "10000.50"),
    ("1 000", "1000"), ("10 000", "10000"), ("100 000", "100000"),
    ("1 000 000", "1000000"), ("10 000,50", "10000.50"),
    ("10 000.50", "10000.50"), ("10,000", "10.000"),
])
def test_parser_validates_numbers_before_decimal_normalization(token, expected):
    parsed = LeadFunnelCalculator().parse(f"Рассчитай лиды при бюджете {token} и CPL 500")
    assert parsed == FunnelInput(budget=Decimal(expected), cpl=Decimal("500"))


@pytest.mark.parametrize("message", [
    "Рассчитай лиды при бюджете 10000 ₽ и CPL 500",
    "Рассчитай лиды при бюджете 10000 и CPL 500рублей",
    "   Рассчитай   количество   лидов  при  бюджете  10   000  руб.  и  CPL  500 руб.   ",
])
def test_parser_one_currency_marker_and_ordinary_spaces(message):
    assert LeadFunnelCalculator().parse(message) == FunnelInput(budget=Decimal("10000"), cpl=Decimal("500"))


@pytest.mark.parametrize("message", [
    "Рассчитай лиды при бюджете 10000, CPC 50 и конверсии 5%",
    "Рассчитай количество лидов при бюджете 10 000 ₽, CPC 50 ₽ и конверсии 5%",
    "Рассчитай сколько лидов при бюджете 10 000руб., cPc 50рублей и конверсии 5%",
])
def test_parser_cpc_currency_formula(message):
    calculator = LeadFunnelCalculator()
    parsed = calculator.parse(message)
    assert parsed == FunnelInput(budget=Decimal("10000"), cpc=Decimal("50"), conversion_rate_percent=Decimal("5"))
    output = calculator.execute(parsed)
    assert output.clicks == Decimal("200")
    assert output.leads == Decimal("10")


@pytest.mark.parametrize("wording", ["лиды", "количество лидов", "сколько лидов"])
def test_parser_traffic_formula(wording):
    calculator = LeadFunnelCalculator()
    parsed = calculator.parse(f"Рассчитай {wording} при трафике 2 000 и конверсии 5%")
    assert parsed == FunnelInput(traffic=Decimal("2000"), conversion_rate_percent=Decimal("5"))
    assert calculator.execute(parsed).leads == Decimal("100")


@pytest.mark.parametrize("token", [
    "100-200", "100–200", "от 100 до 200", "-100", "+100", "10000 20000",
    "1 00", "10 00", "100 00", "1 0000", "12 34 567", "1 00 000", "10 000 00",
    "10,5,5", "10..5", "10,,5", "1e5", "10_000", "10,000,000",
])
def test_parser_rejects_invalid_numeric_tokens(token):
    with pytest.raises(ToolInputNeeded):
        LeadFunnelCalculator().parse(f"Рассчитай лиды при бюджете {token} и CPL 500")


@pytest.mark.parametrize("token", ["100-200", "100–200", "-100", "+100", "10 00", "1 00 000", "10,5,5", "1e5", "10_000"])
@pytest.mark.parametrize("template", [
    "Рассчитай лиды при бюджете 10000 и CPL {token}",
    "Рассчитай лиды при бюджете 10000, CPC {token} и конверсии 5%",
    "Рассчитай лиды при трафике {token} и конверсии 5%",
    "Рассчитай лиды при трафике 2000 и конверсии {token}%",
])
def test_parser_numeric_grammar_is_shared_by_all_fields(token, template):
    with pytest.raises(ToolInputNeeded):
        LeadFunnelCalculator().parse(template.format(token=token))


@pytest.mark.parametrize("message", [
    "Рассчитай лиды при бюджете 100 ₽ и CPL 10 долларов",
    "Рассчитай лиды при бюджете 100 рублей и CPL 10 EUR",
    "Рассчитай лиды при бюджете 100 долларов или 200 евро и CPL 10",
    "Рассчитай лиды при бюджете 10000 и CPL 500 и CPC 50",
    "Рассчитай лиды при бюджете 10000 и CPL 500 и трафике 2000",
    "Рассчитай лиды при бюджете 10000 и CPL 500 и ещё что-нибудь",
    "Пожалуйста, Рассчитай лиды при бюджете 10000 и CPL 500",
    "Рассчитай лиды при трафике 2000 ₽ и конверсии 5%",
    "Рассчитай лиды при трафике 2000руб. и конверсии 5%",
    "Рассчитай лиды при трафике 2000 и конверсии 5₽%",
    "Рассчитай лиды при бюджете 10000 ₽, CPC 50 ₽ и конверсии 5 руб.%",
    "Рассчитай лиды при трафике 2000 и конверсии 5% рублей",
    "Рассчитай лиды при бюджете ₽10000 и CPL 500",
])
def test_parser_rejects_extra_content_and_nonmonetary_currency(message):
    with pytest.raises(ToolInputNeeded):
        LeadFunnelCalculator().parse(message)


@pytest.mark.parametrize("whitespace", ["\n", "\r", "\t", "\u00a0", "\u202f", "\u200b", "\ufeff"])
@pytest.mark.parametrize("position", ["leading", "trailing", "words", "number"])
def test_parser_rejects_hidden_or_structural_whitespace(whitespace, position):
    message = "Рассчитай лиды при бюджете 10000 и CPL 500"
    if position == "leading":
        message = whitespace + message
    elif position == "trailing":
        message += whitespace
    elif position == "words":
        message = message.replace("лиды при", f"лиды{whitespace}при")
    else:
        message = message.replace("10000", f"10{whitespace}000")
    with pytest.raises(ToolInputNeeded):
        LeadFunnelCalculator().parse(message)


@pytest.mark.parametrize("message", [
    "Рассчитай лиды при бюджете 10000 ₽ и CPL 0 ₽",
    "Рассчитай лиды при бюджете 10000 ₽, CPC 0 ₽ и конверсии 5%",
    "Рассчитай лиды при трафике 2000 и конверсии 101%",
    "Рассчитай лиды при бюджете 10000000000000000 ₽ и CPL 500 ₽",
])
def test_parser_preserves_typed_range_validation(message):
    with pytest.raises(ValidationError):
        LeadFunnelCalculator().parse(message)


@pytest.mark.parametrize("message,expected", [
    ("Рассчитай лиды при бюджете 0 ₽ и CPL 500 ₽", "0"),
    ("Рассчитай лиды при трафике 0 и конверсии 5%", "0"),
    ("Рассчитай лиды при трафике 10 и конверсии 0%", "0"),
    ("Рассчитай лиды при трафике 10 и конверсии 100%", "10"),
])
def test_parser_preserves_valid_zero_and_rate_boundaries(message, expected):
    calculator = LeadFunnelCalculator()
    assert calculator.execute(calculator.parse(message)).leads == Decimal(expected)
