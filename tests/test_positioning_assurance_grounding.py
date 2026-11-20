"""Product evidence presence does not authorize guarantees or qualifications."""
from types import SimpleNamespace

import pytest

from app.module_execution.executors.positioning import PositioningExecutor
from app.module_execution.executors.common import StatementSemanticsError, SemanticRule
from app.module_execution.executors.positioning_assurance import has_product_assurance
from app.module_execution.executors.schemas import OutputStatement


def statement(text, output="positioning_statement", kind="INFERENCE", refs=("product",), parents=()):
    return OutputStatement(output_name=output, text=text, kind=kind, confidence="MEDIUM",
        evidence_ids=list(refs), parent_claim_ids=list(parents))


def sources():
    return {"product": SimpleNamespace(input_key="product_truth", value=
        "Проводим занятия с мастером; материалы и обжиг включены; изделие забирают после обжига.")}


@pytest.mark.parametrize("text,output", [
    ("Для новичков с гарантией получить готовое изделие — мастерская глины.", "positioning_statement"),
    ("Поддержка: занятия ведёт опытный мастер, запись через сообщения.", "message_hierarchy"),
    ("Guaranteed finished product with an experienced instructor.", "offer"),
])
def test_observed_promotional_strengthening_is_rejected(text, output):
    with pytest.raises(StatementSemanticsError) as caught:
        PositioningExecutor(model_call=None).validate_statement(statement(text, output), sources(), {})
    assert caught.value.rule is SemanticRule.PRODUCT_ASSURANCE_SUPPORT_REQUIRED


@pytest.mark.parametrize("text", ["ГАРАНТИРОВАННЫЙ результат.", "Гарантируем готовое изделие.",
    "Квалифицированная команда.", "Сертифицированные преподаватели.", "Профессиональный мастер.",
    "Безусловный результат.", "A qualified instructor.", "Certified teachers.",
    "Professional instruction.", "An unconditional promise."])
@pytest.mark.parametrize("kind", ["INFERENCE", "HYPOTHESIS", "RECOMMENDATION"])
def test_promotional_word_families_cannot_be_laundered_by_kind(text, kind):
    with pytest.raises(StatementSemanticsError) as caught:
        PositioningExecutor(model_call=None).validate_statement(statement(text, kind=kind), sources(), {})
    assert caught.value.rule is SemanticRule.PRODUCT_ASSURANCE_SUPPORT_REQUIRED


@pytest.mark.parametrize("category", ["product_truth", "existing_proof"])
def test_exact_cited_owner_qualification_is_allowed_without_rewriting(category):
    text = "Занятия проводит опытный мастер."
    local = {"product": SimpleNamespace(input_key=category, value=text)}
    value = statement(text)
    before = value.model_dump()
    PositioningExecutor(model_call=None).validate_statement(value, local, {})
    assert value.model_dump() == before


@pytest.mark.parametrize("category", ["message", "product", "target_or_target_hypothesis"])
def test_other_context_uncited_source_and_parent_do_not_authorize_qualification(category):
    text = "An experienced master."
    local = sources()
    local["other"] = SimpleNamespace(input_key=category, value=text)
    local["uncited"] = SimpleNamespace(input_key="existing_proof", value=text)
    parents = {"parent": SimpleNamespace(value=text)}
    with pytest.raises(StatementSemanticsError):
        PositioningExecutor(model_call=None).validate_statement(
            statement(text, refs=("product", "other"), parents=("parent",)), local, parents)


@pytest.mark.parametrize("text", ["Проверить опыт участников после занятия.",
    "Test the participant experience before scaling.", "A clay workshop with a master."])
def test_unqualified_reasoning_and_experiments_remain_available(text):
    PositioningExecutor(model_call=None).validate_statement(statement(text), sources(), {})


def test_entire_statement_not_just_matching_qualification_must_be_supported():
    local = {"product": SimpleNamespace(input_key="product_truth", value="An experienced master.")}
    with pytest.raises(StatementSemanticsError):
        PositioningExecutor(model_call=None).validate_statement(
            statement("An experienced master ensures a finished product without further actions."), local, {})


def test_target_can_describe_audience_needs_using_audience_evidence():
    text = "Новички хотят освоить основы фотографии."
    local = {"audience": SimpleNamespace(input_key="target_or_target_hypothesis", value=text)}
    PositioningExecutor(model_call=None).validate_statement(
        statement(text, output="target", refs=("audience",)), local, {})


NO_PURCHASE = "без необходимости покупать профессиональное оборудование"
EQUIPMENT_TRUTH = "Для занятий не требуется профессиональное оборудование."


@pytest.mark.parametrize("category", ["product_truth", "existing_proof"])
@pytest.mark.parametrize("text", [
    f"Курс для начинающих {NO_PURCHASE}.",
    "Курс без необходимости купить профессиональное оборудование.",
    "Курс без необходимости приобретать профессиональное оборудование.",
    "Курс без необходимости приобретения профессионального оборудования.",
    "Курс без необходимости покупки профессионального оборудования.",
    "Для курса не нужно приобретать профессиональное оборудование.",
    "Для курса не требуется покупать профессиональное оборудование.",
    "Для курса нет необходимости приобрести профессиональное оборудование.",
])
def test_no_equipment_purchase_paraphrase_with_cited_product_evidence(text, category):
    local = {"product": SimpleNamespace(input_key=category, value=EQUIPMENT_TRUTH)}
    assert not has_product_assurance(text)
    PositioningExecutor(model_call=None).validate_statement(statement(text, output="target"), local, {})


@pytest.mark.parametrize("category", ["product_truth", "existing_proof"])
@pytest.mark.parametrize("refs,product", [
    (("audience",), EQUIPMENT_TRUTH),
    (("audience", "product"), "Курс для начинающих."),
    (("audience", "product"), "Для занятий требуется профессиональное оборудование."),
    (("audience", "product"), "Правда ли, что для занятий не требуется профессиональное оборудование?"),
])
def test_no_equipment_purchase_requires_support_from_cited_product_evidence(refs, product, category):
    text = f"Курс для начинающих {NO_PURCHASE}."
    local = {
        "product": SimpleNamespace(input_key=category, value=product),
        "audience": SimpleNamespace(input_key="target_or_target_hypothesis", value=EQUIPMENT_TRUTH),
    }
    with pytest.raises(StatementSemanticsError) as caught:
        PositioningExecutor(model_call=None).validate_statement(
            statement(text, output="target", refs=refs), local, {})
    assert caught.value.rule is SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH


@pytest.mark.parametrize("text", [
    f"Курс {NO_PURCHASE} ведёт профессиональный преподаватель.",
    f"Курс {NO_PURCHASE}: предоставляем профессиональное оборудование.",
    f"Курс {NO_PURCHASE} гарантирует результат.",
    "Для занятий обязательно купить профессиональное оборудование.",
    "Курс требует покупки профессионального оборудования.",
    "Курс с необходимостью покупать профессиональное оборудование.",
])
def test_equipment_purchase_exception_does_not_mask_affirmative_assurances(text):
    local = {"product": SimpleNamespace(input_key="product_truth", value=EQUIPMENT_TRUTH)}
    with pytest.raises(StatementSemanticsError) as caught:
        PositioningExecutor(model_call=None).validate_statement(statement(text, output="target"), local, {})
    assert caught.value.rule is SemanticRule.PRODUCT_ASSURANCE_SUPPORT_REQUIRED


def test_exact_rtb_quote_can_contain_equipment_purchase_negation():
    text = f"Курс для начинающих {NO_PURCHASE}."
    local = {"product": SimpleNamespace(input_key="existing_proof", value=text)}
    PositioningExecutor(model_call=None).validate_statement(statement(text, output="RTB"), local, {})


def test_rejection_on_dispatch_is_bounded_and_does_not_retry_or_repair(monkeypatch):
    from unittest.mock import Mock
    from app.module_execution.executors import common
    from tests.test_module_executors import FakeModel, request, dispatch
    from app.module_registry import ModuleId
    from app.module_execution.executors import ExecutorOutputError
    warning = Mock()
    monkeypatch.setattr(common.log, "warning", warning)
    model = FakeModel(lambda p, d: p["outputs"][0].update(text="Guaranteed result."))
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(request(ModuleId.POSITIONING, outputs=("offer",)), model)
    assert caught.value.stage.value == "statement_semantics_invalid"
    warning.assert_called_once_with("Module output rejected module=%s stage=%s rule=%s",
        "POSITIONING", "statement_semantics_invalid", "product_assurance_support_required")
    assert "Guaranteed result" not in str(warning.call_args) + str(caught.value)
    assert len(model.calls) == 1
