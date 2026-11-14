"""Explicit owner-grounded bet recipes; canonical source and hypothesis stay separate."""
from copy import deepcopy

from app.module_execution.errors import ModuleExecutionContractError
from .cmo_source_selection import TERMS_PREFIX


BET_DEFINITION = "CMOSourceBoundBetStatement"
BET_INTROS = (
    "Рабочая ставка — проверить реакцию аудитории на полное предоставленное описание условий; результат пока неизвестен.",
    "Test the audience response to the complete supplied owner terms; the result remains unknown.",
)
BET_RELATIONS = {
    "audience_value_ru": "Гипотеза для проверки: аудитория называет предоставленные условия важной причиной интереса к предложению; проверить это в беседах без предположения о результате.",
    "message_understanding_ru": "Гипотеза для проверки: аудитория пересказывает предоставленные условия без дополнительных обещаний; сопоставить её понимание с полным описанием владельца.",
    "message_preference_ru": "Гипотеза для проверки: сообщение с полным описанием условий вызывает более предметные вопросы, чем нейтральное описание; подготовить и согласовать сравнительный тест с владельцем.",
    "audience_value_en": "Test the hypothesis that the audience names the supplied terms as a reason for interest; ask in interviews without presuming the answer.",
    "message_understanding_en": "Test whether the audience restates the supplied terms without adding promises; compare its understanding with the complete owner description.",
    "message_preference_en": "Test whether the complete terms prompt more specific questions than a neutral description; prepare and agree the comparison with the owner first.",
}


def owner_bet_choices(source_choices, owner_terms=None):
    """Project the already validated typed catalogs, never infer authority from prose.

    SOURCE choices render complete qualitative owner terms as an item. TERMS
    choices (complete owner terms containing a quantity) render only as an
    exact numeric_context quote, because canonical items stay digit-free.
    """
    choices = {key: row for key, row in source_choices.items()
               if row["input_key"] in {"product_truth", "confirmed_business_fact"}
               and row["source_class"] == "FIRST_PARTY" and len(row["text"]) <= 300}
    choices.update((key, row) for key, row in (owner_terms or {}).items() if key.startswith(TERMS_PREFIX))
    return dict(sorted(choices.items()))


def source_bet_statement_schema(base, choices):
    result = deepcopy(base)
    props = result["properties"]
    props["text"] = {"type": "string", "minLength": 1, "maxLength": 4000,
                     "enum": list(BET_INTROS),
                     "description": "Prospective summary only; the explicit source and testable bet are separate items."}
    props["kind"] = {"type": "string", "const": "HYPOTHESIS"}
    props["confidence"] = {"type": "string", "enum": ["UNKNOWN"]}
    props["items"] = {"type": "array", "minItems": 1, "maxItems": 1,
        "description": ("Choose one complete owner source and an observable audience/message hypothesis about the FULL supplied terms, not an isolated condition or a proven result. "
                        "A SOURCE choice renders the complete terms as an item; a TERMS choice renders the complete terms, including their quantities, only as an exact numeric_context quote."),
        "items": {"type": "object", "properties": {
            "source_choice": {"type": "string", "enum": sorted(choices)},
            "test_relation": {"type": "string", "enum": list(BET_RELATIONS)},
        }, "required": ["source_choice", "test_relation"], "additionalProperties": False}}
    return result


def render_source_bet(item, choices):
    if (type(item) is not dict or set(item) != {"source_choice", "test_relation"}
            or type(item["source_choice"]) is not str or item["source_choice"] not in choices
            or type(item["test_relation"]) is not str or item["test_relation"] not in BET_RELATIONS):
        raise ModuleExecutionContractError("Invalid CMO source-bound bet")
    row = choices[item["source_choice"]]
    relation = BET_RELATIONS[item["test_relation"]]
    if item["source_choice"].startswith(TERMS_PREFIX):
        return [relation], row["evidence_id"], [{"support_id": row["evidence_id"], "quote": row["text"]}]
    return [row["text"], relation], row["evidence_id"], []
