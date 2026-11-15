"""Provider-only language projection: Russian requests get Russian generation."""
import hashlib
import json
import re
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from app.module_execution.executors import provider_language as language
from app.module_execution.executors.cmo_demo_plans import DEMO_FREE_PATTERN, PLAN_NOTES
from app.module_execution.executors.provider_schema import nodes
from app.module_execution.executors.numeric_quantity import has_numeric_quantity
from app.module_execution.executors.qualitative_generation import QUALITATIVE_GENERATION_PATTERN
from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
from tests.test_cmo_support_wire import contracts, scoped_request, wire_output
from app.module_execution.executors.cmo_support_wire import support_selection_catalog

RU = (language.RU_QUALITATIVE_PATTERN, language.RU_CMO_PATTERN)
# Observed in the multi-domain live acceptance on 196cb37.
OBSERVED = (
    "Согласование с владельцем двухвариантных текстов (контрольного и тестового) до проведения бесед.",
    "HYPOTHESIS: Для аудитории ясное сообщение увеличит готовность записаться заранее.",
    "RECOMMENDATION: Не вводить числовые пороги.",
    "target_metric: готовность записаться заранее",
    "Hypnosis: audience reaction and reasons for contact remain unvalidated.",
    "HYPOT HYP: prioritize testing message variants.",
    "Баланс между скоростью проверки и точностью product description.",
    "Working diagnosis: there may be a gap between the supplied sample and the audience.",
    # 6778cd7, bakery: ASCII digits were excluded, so the time came out in Arabic-Indic digits.
    'Полное подтверждённое формулирование условий владельца: "заказ принимается до ۱۸:۰۰ накануне"',
    "ＨＹＰ проверить спрос", "Проверить спрос ✅", "шаг + условия", "Строка" + chr(10) + "вторая",
)


def request(*values, objective="Проверить интерес к предложению", constraints=()):
    facts = tuple(SimpleNamespace(authorized=True, value=value) for value in values)
    return SimpleNamespace(objective=objective, context_packet=SimpleNamespace(
        constraints=constraints, relevant_project_context=facts, known_facts=()))


@pytest.mark.parametrize("pattern", RU)
@pytest.mark.parametrize("text", OBSERVED + ("audience_understanding_ru", "трёхэтапная проверка", "две версии",
                                             "Проверить Telegram канал", "Провести 3 беседы"))
def test_observed_generation_defects_cannot_be_generated_for_a_russian_request(pattern, text):
    assert re.fullmatch(pattern, text) is None


@pytest.mark.parametrize("text", [
    "Провести беседы с жителями района о предзаказе.",
    "Рекомендуем сохранить полные условия владельца; гипотезу проверить в беседах.",
    "Качественные интервью — понимание, причины, сомнения.",
    "Сравнить контрольное и тестовое сообщения на сопоставимой аудитории",
    "Провести беседы (очно), затем — сравнить «ответы»; из‑за сроков.",
])
def test_ordinary_russian_prose_is_available_and_valid_for_the_unchanged_wire(text):
    for pattern in RU:
        assert re.fullmatch(pattern, text)
    # Narrowing only: whatever the provider may generate is valid for the authoritative wire patterns.
    assert re.fullmatch(QUALITATIVE_GENERATION_PATTERN, text) and re.fullmatch(DEMO_FREE_PATTERN, text)
    assert not has_numeric_quantity(text)


def test_experiments_prose_cannot_embed_a_demo_quotation():
    # 33e6918, course release proof: rejected downstream with DEMONSTRATION_ASSERTION_REQUIRES_SOURCE.
    observed = ('Документировать полные тексты сообщений, полные заметки бесед с аудиторией, '
                'и точную цитату: "Демонстрационный образец показывает сравнение снимков."')
    assert re.fullmatch(language.RU_QUALITATIVE_PATTERN, observed) is None
    assert re.fullmatch(language.RU_QUALITATIVE_PATTERN, "Показать предоставленный образец в беседе и записать реакцию.")
    # Equipment stays a CMO-only closure.
    assert re.fullmatch(language.RU_QUALITATIVE_PATTERN, "Уточнить оборудование у владельца")


def test_cmo_pattern_keeps_the_demo_and_equipment_classes_closed():
    for text in ("Новый демонстрационный материал", "Уточнить оборудование у владельца", "демо для аудитории"):
        assert re.fullmatch(language.RU_CMO_PATTERN, text) is None
        assert re.fullmatch(DEMO_FREE_PATTERN, text) is None


def test_patterns_are_the_ones_the_provider_accepted():
    # Offline tests cannot observe provider acceptance (an unsupported pattern returns an empty
    # incomplete response). Both exact patterns completed on 15.11.2026 in one five-field schema
    # (req_d32ef29ee0984035a6a5b148829d221d); the qualitative pattern with the demo vocabulary
    # closed completed in req_62cf3c1513b7423da48279f0723fa9be. Re-probe before changing a pin.
    assert hashlib.sha256(language.RU_CMO_PATTERN.encode()).hexdigest().startswith("b4a71bcffe157460")
    assert hashlib.sha256(language.RU_QUALITATIVE_PATTERN.encode()).hexdigest().startswith("09dcc8cfeb12dcb9")
    assert "[^" not in language.RU_QUALITATIVE_PATTERN and "[^" not in language.RU_CMO_PATTERN
    for pattern in RU:
        assert ")+" not in pattern and "(?!" not in pattern and "(?=" not in pattern and pattern.count("$") == 1


def test_request_language_follows_the_owner_inputs_not_markers_or_server_text():
    assert language.request_language(request("пекарни «KHLEBQOLHTGDR», которая продаёт хлеб по предзаказу.")) == "ru"
    assert language.request_language(request("Bakery with weekend preorders", objective="Test demand")) is None
    assert language.request_language(request(objective="Validate interest")) is None
    unauthorized = request("Bakery", objective="Demand")
    unauthorized.context_packet.relevant_project_context = (SimpleNamespace(authorized=False, value="пекарня" * 9),)
    assert language.request_language(unauthorized) is None


def cmo_provider_schema(monkeypatch, value):
    monkeypatch.setattr(language, "request_language", lambda _request: value)
    req = scoped_request()
    canonical, wire, ids, parents, catalog = contracts(req)
    provider = VirtualCMOExecutor(model_call=None, support_selection_wire=True).provider_schema_for(req, wire)
    return req, wire, provider, support_selection_catalog(ids, parents)


def prose_values(schema):
    return [value for node in nodes(schema) if isinstance(node.get("enum"), list)
            for value in node["enum"] if isinstance(value, str) and " " in value]


def test_russian_request_gets_russian_closed_sentences_keys_and_patterns(monkeypatch):
    req, wire, provider, _ = cmo_provider_schema(monkeypatch, "ru")
    protected = language._request_strings(req)
    english = [value for value in prose_values(provider) if not re.search("[А-Яа-яЁё]", value) and value not in protected]
    assert english == []
    assert any(not re.search("[А-Яа-яЁё]", value) for value in prose_values(wire))  # the wire still offers both
    keys = [value for node in nodes(provider) for value in node.get("enum", []) if isinstance(value, str)]
    assert any(key.endswith("_ru") for key in keys) and not any(key.endswith("_en") for key in keys)
    patterns = {node["pattern"] for node in nodes(provider) if "pattern" in node}
    assert language.RU_CMO_PATTERN in patterns and DEMO_FREE_PATTERN not in patterns
    assert not any(note in prose_values(provider) for note in PLAN_NOTES if not re.search("[А-Яа-яЁё]", note))
    Draft202012Validator.check_schema(provider)
    assert wire == contracts(req)[1]  # the authoritative wire schema is not mutated


def test_projection_is_identity_for_other_languages(monkeypatch):
    _, wire, provider, _ = cmo_provider_schema(monkeypatch, None)
    assert provider == wire


def test_projection_only_narrows_what_the_wire_accepts(monkeypatch):
    req, wire, provider, choices = cmo_provider_schema(monkeypatch, "ru")
    payload = wire_output(req.expected_outputs, choices)
    if Draft202012Validator(provider).is_valid(payload):
        assert Draft202012Validator(wire).is_valid(payload)
    # A Russian free text accepted by the provider schema is accepted by the wire schema.
    name = req.expected_outputs[0]
    for candidate in (payload,):
        candidate = json.loads(json.dumps(candidate))
        candidate["outputs"][name]["text"] = "Проверить понимание условий в беседах с аудиторией."
        assert Draft202012Validator(wire).is_valid(candidate) or not Draft202012Validator(provider).is_valid(candidate)


def test_owner_texts_are_never_removed_and_unsatisfiable_schemas_fall_back(monkeypatch):
    monkeypatch.setattr(language, "request_language", lambda _request: "ru")
    owner = request("Only pickup, no delivery", "хлеб забирают самовывозом")
    owner.upstream_results = ()
    monkeypatch.setattr(language, "plain", lambda packet: {"facts": [fact.value for fact in packet.relevant_project_context]})
    schema = {"type": "object", "properties": {
        "constraints": {"type": "array", "minItems": 2, "items": {"type": "string",
                        "enum": ["Only pickup, no delivery", "хлеб забирают самовывозом"]}},
        "note": {"type": "string", "enum": ["Проверить спрос в беседах.", "Check demand in interviews."]},
        "relation": {"type": "string", "enum": ["value_ru", "value_en"]}}}
    projected = language.language_projection(schema, owner)
    assert projected["properties"]["constraints"]["items"]["enum"] == schema["properties"]["constraints"]["items"]["enum"]
    assert projected["properties"]["note"]["enum"] == ["Проверить спрос в беседах."]
    assert projected["properties"]["relation"]["enum"] == ["value_ru"]
    broken = {"type": "array", "minItems": 2, "items": {"type": "string",
              "enum": ["Проверить спрос в беседах.", "Check demand in interviews."]}}
    assert language.language_projection(broken, owner) is broken


def test_model_input_names_the_output_language_only_for_russian(monkeypatch):
    monkeypatch.setattr(language, "request_language", lambda _request: "ru")
    data = language.with_output_language({"objective": "x"}, object())
    assert data["output_language"] == "ru" and "Cyrillic" in data["output_language_guidance"]
    monkeypatch.setattr(language, "request_language", lambda _request: None)
    assert language.with_output_language({"objective": "x"}, object()) == {"objective": "x"}
