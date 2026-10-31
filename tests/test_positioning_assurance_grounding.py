"""Product evidence presence does not authorize guarantees or qualifications."""
from types import SimpleNamespace

import pytest

from app.module_execution.executors.positioning import PositioningExecutor
from app.module_execution.executors.common import StatementSemanticsError, SemanticRule
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


def test_rejection_on_dispatch_is_bounded_and_does_not_retry_or_repair(caplog):
    from tests.test_module_executors import FakeModel, request, dispatch
    from app.module_registry import ModuleId
    from app.module_execution.executors import ExecutorOutputError
    model = FakeModel(lambda p, d: p["outputs"][0].update(text="Guaranteed result."))
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(request(ModuleId.POSITIONING, outputs=("offer",)), model)
    assert caught.value.stage.value == "statement_semantics_invalid"
    assert "rule=product_assurance_support_required" in caplog.text
    assert "Guaranteed result" not in caplog.text + str(caught.value)
    assert len(model.calls) == 1
