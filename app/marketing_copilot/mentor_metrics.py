"""Conservative arithmetic over explicitly labelled user reports, never model math."""
import re
from decimal import Decimal, InvalidOperation


def analyze_metrics(metrics, notes=""):
    text = metrics.strip() or notes.strip()
    result = {"verification": "user_reported", "calculations": {}, "clarifications": [],
              "limitations": ["Данные сообщил пользователь; причинный эффект и окупаемость не установлены."]}
    # Require one labelled observation per field. Do not infer counts from prose,
    # platform names, dates, percentages, baselines or multiple reporting periods.
    fields = {}
    for part in re.split(r"[;\n]", text):
        match = re.fullmatch(r"\s*(расход|заявки|продажи|период)\s*:?\s+(.+?)\s*", part, re.I)
        if not match or match[1].lower() in fields:
            result["clarifications"].append("Укажите однозначно: Расход: число и валюта; Заявки: число; Продажи: число; Период: один общий период.")
            return result
        fields[match[1].lower()] = match[2]
    if not all(key in fields for key in ("расход", "заявки", "продажи")):
        result["clarifications"].append("Нужны расход с валютой, число заявок и число продаж за один общий период.")
        return result
    spend = re.fullmatch(r"((?:\d{1,12}|\d{1,3}(?:[ \u00a0]\d{3}){1,3})(?:[.,]\d{1,2})?)\s*(₽|RUB|руб\.?|USD|\$|EUR|€)", fields["расход"], re.I)
    if not spend or not all(re.fullmatch(r"\d{1,9}", fields[key]) for key in ("заявки", "продажи")):
        result["clarifications"].append("Проверьте неотрицательные суммы, валюту и целые количества заявок/продаж; не смешивайте единицы.")
        return result
    try:
        amount = Decimal(spend[1].replace(" ", "").replace("\u00a0", "").replace(",", "."))
        leads, sales = int(fields["заявки"]), int(fields["продажи"])
    except (InvalidOperation, ValueError):
        result["clarifications"].append("Не удалось однозначно прочитать числа.")
        return result
    if sales > leads:
        result["clarifications"].append("Продаж больше заявок: уточните, относятся ли продажи к этим заявкам.")
        return result
    currency = {"₽": "RUB", "руб": "RUB", "руб.": "RUB", "$": "USD", "€": "EUR"}.get(spend[2].lower(), spend[2].upper())
    result.update(currency=currency, period=fields.get("период"), inputs={"spend": str(amount), "leads": leads, "sales": sales})
    if not fields.get("период"):
        result["clarifications"].append("Укажите общий период и подтвердите, что продажи относятся к указанным заявкам; до уточнения метрики не рассчитаны.")
        return result
    def number(value):
        return format(value.quantize(Decimal("0.01")), "f").rstrip("0").rstrip(".")
    if leads:
        result["calculations"]["cost_per_lead"] = number(amount / leads) + " " + currency
        result["calculations"]["lead_to_sale_conversion"] = number(Decimal(sales) / leads * 100) + "%"
    else:
        result["clarifications"].append("При нуле заявок CPL и конверсия не определены.")
    if sales:
        result["calculations"]["cost_per_sale"] = number(amount / sales) + " " + currency
    else:
        result["clarifications"].append("При нуле продаж стоимость привлечения продажи не определена.")
    return result
