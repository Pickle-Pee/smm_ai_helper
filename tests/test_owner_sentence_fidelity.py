"""An owner sentence is quoted exactly or not at all; a misspelt demo word is still a demo word.

Production acceptance on 91a0589 (16.11.2026) accepted a misspelt copy of the owner's
demonstration sentence in EXPERIMENTS minimum_required_inputs in three runs of three.
"""
import asyncio
from dataclasses import replace
import json
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from app.marketing_orchestrator.quality_gates.contracts import EvidenceSourceClass
from app.module_execution.acceptance import fully_accepted
from app.module_execution.executors import ExperimentsExecutor
from app.module_execution.executors import provider_language as language
from app.module_execution.executors.common import (
    ExecutorOutputError, OutputFailureStage, SemanticRule, StatementSemanticsError,
)
from app.module_execution.executors.downstream_fidelity import (
    distorted_demo_mention, mentions_demo, reject_distorted_source_copy, validate_leaf,
)
from app.module_execution.executors.experiments import (
    REQUIRED_INPUT_SOURCE_DEFINITION, required_input_source_choices,
)
from app.orchestration_runtime.service import evaluate_result
from tests.test_experiments_support_selection import typed_payload
from tests.test_experiments_support_wire import invocation  # noqa: F401  (fixture)
from tests.test_module_executors import fact

COURSE = "Есть демонстрационный образец, который показывает сравнение снимков."
BAKERY = "Есть демонстрационный образец — фотография набора из трёх видов хлеба."
GROOMING = "Есть демонстрационный образец — фотографии одной собаки до и после стрижки"
TERMS = "заказ принимается до 18:00 накануне; хлеб забирают самовывозом из пекарни в субботу утром, доставки нет."
# Accepted by production on 91a0589, and by the multi-domain run on 33e6918.
ACCEPTED_DISTORTIONS = (
    (COURSE, "Есть демонтрационный образец, который показывает сравнение снимков."),
    (BAKERY, "Есть демонрационный образец — фотография набора из трё х видов хлеба."),
    (GROOMING, "Есть демонтрационный образец — фотографии одной собаки до и после стрижки"),
    (BAKERY, "Есть демонстрационный образец — фотография набора из трёёх видов хлеба."),
    # Both release proofs of 91a0589 (course, ceramics): the sentence itself asserts what the demo shows.
    ("Демонстрационный образец показывает сравнение снимков.", "Демонистрационный образец показывает сравнение снимков."),
    ("Демонстрационный образец показывает вариант глазурования чаши.",
     "Демонистрационный образец показывает вариант глазурования чаши."),
)
OBSERVED_WORDS = ("демонрационный", "демонтрационным", "демонормационный", "демондикационный", "демонтации",
                  "Демонрационного", "демонрации", "Демонистрационный")


RUSSIAN_CONTEXT = ("Владелец описывает предложение своими словами и просит проверить интерес аудитории, "
                   "причины обращения и понятность условий до любых расходов на продвижение.")


def source(value, key="existing_proof", source_class=EvidenceSourceClass.FIRST_PARTY):
    return SimpleNamespace(input_key=key, value=value, record=SimpleNamespace(source_class=source_class))


@pytest.mark.parametrize("word", OBSERVED_WORDS)
def test_observed_misspellings_are_demo_mentions(word):
    assert distorted_demo_mention("Показать " + word + " образец в беседе.")
    assert mentions_demo("Показать " + word + " образец в беседе.")


@pytest.mark.parametrize("text", [
    "Показать демон страцию в беседе.", "Собрать реакции на демонст рационный образец."])
def test_split_demo_word_is_a_demo_mention(text):
    assert mentions_demo(text)


@pytest.mark.parametrize("text", [
    "Провести демонтаж старой витрины перед открытием.", "Демонтировать вывеску и согласовать новую.",
    "Уточнить демографию района и привычки покупателей.", "Демократичные цены как гипотеза для проверки.",
    "Избегать демпинга и проверять готовность платить.", "Демисезонная коллекция как предмет беседы.",
    "Проверить, нет ли демонизации конкурентов в сообщении.", "Собрать реакции на предоставленный образец."])
def test_ordinary_words_are_not_demo_mentions(text):
    assert not distorted_demo_mention(text)
    assert not mentions_demo(text)


def test_exact_demo_word_keeps_its_existing_recognition():
    assert mentions_demo("Показать демонстрационный образец в беседе.")
    assert not distorted_demo_mention("Показать демонстрационный образец в беседе.")


@pytest.mark.parametrize("text", [
    "Качественные разговоры и подготовка демонтации, показывающей разницу снимков.",
    "Использовать существующий демонрационный образец как предмет обсуждения при беседах.",
    "Демонрационный образец подтверждает ценность предложения."])
def test_misspelt_demo_word_no_longer_hides_an_assertion(text):
    with pytest.raises(StatementSemanticsError) as caught:
        validate_leaf(text)
    assert caught.value.rule is SemanticRule.DEMONSTRATION_ASSERTION_REQUIRES_SOURCE


def test_misspelt_reference_without_an_assertion_is_not_made_fatal():
    validate_leaf("Показать демонормационный образец в обсуждении и собрать реакции на понятность условий.")


@pytest.mark.parametrize("original,distorted", ACCEPTED_DISTORTIONS)
def test_distorted_copy_of_an_owner_proof_sentence_is_rejected(original, distorted):
    with pytest.raises(StatementSemanticsError) as caught:
        reject_distorted_source_copy(distorted, {"proof": source(original)})
    assert caught.value.rule is SemanticRule.DEMONSTRATION_ASSERTION_REQUIRES_SOURCE


def test_distorted_copy_of_owner_terms_uses_the_product_rule():
    distorted = TERMS.replace("самовывозом", "самовывзом")
    with pytest.raises(StatementSemanticsError) as caught:
        reject_distorted_source_copy(distorted, {"terms": source(TERMS, "product_truth")})
    assert caught.value.rule is SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH


@pytest.mark.parametrize("text", [
    COURSE, COURSE.rstrip("."), "«" + COURSE + "»", "  " + COURSE.upper() + " ",
    "Записывать реакции на формулировку: " + COURSE,
    "Сценарии бесед с вопросами о причинах обращения и о понятности условий.",
    "Подготовить новое тестовое сообщение и согласовать его с владельцем.",
    "Есть образец."])
def test_exact_copies_embedded_copies_and_other_prose_are_not_distorted_copies(text):
    reject_distorted_source_copy(text, {"proof": source(COURSE), "terms": source(TERMS, "product_truth")})


def test_only_request_local_first_party_owner_sentences_are_compared():
    distorted = ACCEPTED_DISTORTIONS[0][1]
    reject_distorted_source_copy(distorted, {"a": source(COURSE, "business_goal")})
    reject_distorted_source_copy(distorted, {"a": source(COURSE, source_class=EvidenceSourceClass.EXTERNAL_PRIMARY)})
    reject_distorted_source_copy(distorted, {"a": source(["not", "text"])})
    reject_distorted_source_copy("Есть образец!", {"a": source("Есть образец.")})  # below the length floor


def russian(request, demo):
    """The fixture request with Russian owner inputs and an owner demonstration sentence."""
    packet = request.context_packet
    return replace(request, objective="Проверить интерес к предложению и причины обращения.",
                   context_packet=replace(packet, known_facts=(*packet.known_facts, fact("existing_proof", demo),
                       fact("owner_note", RUSSIAN_CONTEXT))))


def captured_schemas(request):
    seen = {}

    class Capture(ExperimentsExecutor):
        def provider_schema_for(self, request, validation_schema):
            seen["wire"] = validation_schema
            seen["provider"] = super().provider_schema_for(request, validation_schema)
            return seen["provider"]

    async def model(**kwargs):
        seen["data"] = json.loads(kwargs["text"])
        return json.dumps(typed_payload(seen["data"], kwargs["response_schema"]))

    asyncio.run(Capture(model_call=model, strategic_parent_wire=True, support_selection_wire=True).execute(request))
    return seen


@pytest.mark.parametrize("demo", [COURSE, BAKERY, GROOMING])
def test_russian_request_can_reach_the_exact_owner_proof_sentence(invocation, demo):
    request = russian(invocation, demo)
    assert language.request_language(request) == "ru"
    seen = captured_schemas(request)
    provider, wire = seen["provider"], seen["wire"]
    items = provider["$defs"]["ExperimentDesign"]["properties"]["minimum_required_inputs"]["items"]
    assert items["anyOf"][-1] == {"$ref": "#/$defs/" + REQUIRED_INPUT_SOURCE_DEFINITION}
    assert provider["$defs"][REQUIRED_INPUT_SOURCE_DEFINITION] == {"type": "string", "enum": [demo]}
    free = [branch for branch in items["anyOf"] if "pattern" in branch]
    assert [branch["pattern"] for branch in free] == [language.RU_QUALITATIVE_PATTERN]
    # Free language-bound prose still cannot spell the sentence; only the closed choice can.
    assert not Draft202012Validator(free[0]).is_valid(demo)
    item = Draft202012Validator({**items, "$defs": provider["$defs"]})
    assert item.is_valid(demo)
    for _, distorted in ACCEPTED_DISTORTIONS[:3]:
        assert distorted == demo or not Draft202012Validator(
            {"$ref": "#/$defs/" + REQUIRED_INPUT_SOURCE_DEFINITION, "$defs": provider["$defs"]}).is_valid(distorted)
    # Narrowing only: the unchanged wire schema accepts the same sentence.
    wire_items = wire["$defs"]["ExperimentDesign"]["properties"]["minimum_required_inputs"]["items"]
    assert Draft202012Validator({**wire_items, "$defs": wire["$defs"]}).is_valid(demo)
    assert REQUIRED_INPUT_SOURCE_DEFINITION not in wire["$defs"]


def test_sentences_the_wire_schema_rejects_are_not_offered(invocation):
    numeric = "Есть демонстрационный образец — 3 фотографии набора."
    seen = captured_schemas(russian(invocation, numeric))
    assert REQUIRED_INPUT_SOURCE_DEFINITION not in seen["provider"]["$defs"]


def test_request_without_an_owner_proof_sentence_keeps_its_schema(invocation):
    seen = captured_schemas(invocation)
    assert REQUIRED_INPUT_SOURCE_DEFINITION not in seen["provider"]["$defs"]
    assert required_input_source_choices(seen["provider"], seen["wire"], ()) is seen["provider"]


def run_with_required_input(request, value, *, select):
    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        payload = typed_payload(data, kwargs["response_schema"])
        if select:
            identity = next(item["evidence_id"] for item in data["local_evidence"] if item["input_key"] == "existing_proof")
            alias = next(key for key, chosen in data["experiments_support_selection_catalog"]["evidence"].items()
                         if chosen == identity)
            next(row for row in payload["outputs"]
                 if row["output_name"] == "evidence_basis")["additional_evidence_support"][alias] = True
        payload["experiments"][0]["minimum_required_inputs"] = [value]
        return json.dumps(payload)

    return asyncio.run(ExperimentsExecutor(model_call=model, strategic_parent_wire=True,
                                           support_selection_wire=True).execute(request))


@pytest.mark.parametrize("demo,select", [(COURSE, True), (BAKERY, True), (BAKERY, False), (GROOMING, False)])
def test_exact_owner_proof_sentence_is_accepted_as_a_required_input(invocation, demo, select):
    request = russian(invocation, demo)
    result = run_with_required_input(request, demo, select=select)
    assert result.payload["experiments"][0]["minimum_required_inputs"] == (demo,)
    quality = evaluate_result(request.execution_id, result, request.upstream_results)
    assert fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])


def test_exact_sentence_that_states_what_the_demo_shows_still_needs_its_selected_source(invocation):
    with pytest.raises(ExecutorOutputError) as caught:
        run_with_required_input(russian(invocation, COURSE), COURSE, select=False)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


@pytest.mark.parametrize("original,distorted", ACCEPTED_DISTORTIONS)
@pytest.mark.parametrize("select", [False, True])
def test_distorted_owner_proof_sentence_is_rejected_as_a_required_input(invocation, original, distorted, select):
    with pytest.raises(ExecutorOutputError) as caught:
        run_with_required_input(russian(invocation, original), distorted, select=select)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


def test_guidance_names_the_neutral_reference_and_the_exact_choice():
    guidance = language.LANGUAGE_GUIDANCE["ru"]
    assert "«предоставленный образец»" in guidance and "listed exact choices" in guidance
    for pattern in (language.RU_QUALITATIVE_PATTERN, language.RU_CMO_PATTERN):
        assert Draft202012Validator({"type": "string", "pattern": pattern}).is_valid(
            "Показать предоставленный образец в беседе и собрать реакции.")
