"""Bounded demo-scope diagnoses; a complete source never proves an audience gap."""
from copy import deepcopy

from app.module_execution.errors import ModuleExecutionContractError


DIAGNOSIS_DEFINITION = "CMOSourceBoundDiagnosisStatement"
DIAGNOSIS_INTROS = (
    "Рабочая диагностическая гипотеза — возможный разрыв между предоставленным образцом и пониманием ценности предложения аудиторией; проверить её, не считая разрыв установленным.",
    "Working diagnosis: there may be a gap between the supplied sample and the audience's understanding of the offer's value; test this without treating the gap as established.",
)
DIAGNOSIS_RELATIONS = {
    "audience_understanding_ru": "Гипотеза для проверки: аудитория может иначе понимать назначение предоставленного образца; выяснить это в интервью без предположения об ответе.",
    "message_connection_ru": "Гипотеза для проверки: связь предоставленного образца с выбранным акцентом сообщения может быть неясна аудитории; проверить эту связь в беседах.",
    "value_relevance_ru": "Гипотеза для проверки: предоставленный образец может не объяснять важность предложения для аудитории; исследовать причины интереса без вывода о результативности продукта.",
    "audience_understanding_en": "Test the hypothesis that the audience may understand the supplied sample differently than intended; ask in interviews without presuming the answer.",
    "message_connection_en": "Test whether the audience understands the connection between the supplied sample and the proposed message emphasis; do not treat a gap as established.",
    "value_relevance_en": "Test whether the supplied sample helps the audience explain why the offer matters to them; investigate reasons for interest without inferring product effectiveness.",
}


def demo_diagnosis_choices(source_choices):
    """Project the validated catalog; preserve its source and quantity eligibility."""
    return {key: row for key, row in source_choices.items()
            if row["input_key"] == "existing_proof" and row["source_class"] == "FIRST_PARTY"
            and len(row["text"]) <= 300}


def source_diagnosis_statement_schema(base, choices):
    result = deepcopy(base)
    props = result["properties"]
    props["text"] = {"type": "string", "minLength": 1, "maxLength": 4000,
                     "enum": list(DIAGNOSIS_INTROS),
                     "description": "Prospective evidence-scope diagnosis, never an established audience gap or product effect."}
    props["kind"] = {"type": "string", "const": "HYPOTHESIS"}
    props["confidence"] = {"type": "string", "enum": ["UNKNOWN"]}
    props["items"] = {"type": "array", "minItems": 1, "maxItems": 1,
        "description": "Select a complete supplied demo and a separate prospective question about audience understanding, message connection or relevance. The sample does not establish an effect.",
        "items": {"type": "object", "properties": {
            "source_choice": {"type": "string", "enum": sorted(choices)},
            "diagnostic_relation": {"type": "string", "enum": list(DIAGNOSIS_RELATIONS)},
        }, "required": ["source_choice", "diagnostic_relation"], "additionalProperties": False}}
    return result


def render_source_diagnosis(item, choices):
    if (type(item) is not dict or set(item) != {"source_choice", "diagnostic_relation"}
            or type(item["source_choice"]) is not str or item["source_choice"] not in choices
            or type(item["diagnostic_relation"]) is not str or item["diagnostic_relation"] not in DIAGNOSIS_RELATIONS):
        raise ModuleExecutionContractError("Invalid CMO source-bound diagnosis")
    row = choices[item["source_choice"]]
    return [row["text"], DIAGNOSIS_RELATIONS[item["diagnostic_relation"]]], row["evidence_id"]
