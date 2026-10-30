"""POSITIONING numerical assertions must quote their own cited support."""
from dataclasses import replace
from unittest.mock import Mock

import pytest

from app.module_execution import UpstreamExecutionResult
from app.module_execution.executors import PositioningExecutor, ExecutorOutputError
from app.module_execution.executors.common import (
    OutputFailureStage, SemanticRule, StatementSemanticsError,
)
from app.module_execution.executors.schemas import OutputStatement
from app.module_registry import ModuleId
from app.orchestration_runtime.worker import transient
from tests.test_module_executors import FakeModel, dispatch, fact, facts_for_module, request


COURSE_TRUTH = "Курс длится 6 недель и включает практические задания."
# Exact provider statement from the synthetic course acceptance; renderer labels
# (recommendation/confidence) are not part of this model text.
UNSUPPORTED_VALIDATION_PLAN = (
    "1) Мини‑пилот: набрать 5–10 первых платных учеников через органику/пост в соцсетях и предложить им полную программу. "
    "2) Метрики: количество оплат, процент завершивших задания, качество обратной связи (внутренняя чек‑листа), полученные до/после снимки. "
    "3) Срок проверки: 1 поток (6 недель) + сбор результатов в конце потока. "
    "4) Критерии решения: если >50% участников выполняют задания и предоставляют улучшенные снимки по внутренней оценке — масштабировать; иначе — скорректировать содержание и формат обратной связи. "
    "5) Быстрые проверки: провести бесплатный пробный разбор 5‑10 снимков как промо и измерить отклик (заявки на полный курс)."
)


def course_request(output="validation_plan.", *, upstream=(), identity=None):
    facts = tuple(replace(item, value=COURSE_TRUTH) if item.label == "product_truth" else item
                  for item in facts_for_module(ModuleId.POSITIONING))
    return request(ModuleId.POSITIONING, facts=facts, outputs=(output,), upstream=upstream, identity=identity)


def model_text(text, *, cited_local=None, use_parents=False, kind="RECOMMENDATION"):
    def mutate(payload, data):
        statement = payload["outputs"][0]
        statement.update(text=text, kind=kind)
        if cited_local is not None:
            statement["evidence_ids"] = [entry["evidence_id"] for entry in data["local_evidence"]
                                         if entry["input_key"] in cited_local]
    return FakeModel(mutate, use_parents=use_parents)


def test_invented_validation_plan_is_rejected_once(monkeypatch):
    from app.module_execution.executors.common import log
    warning = Mock()
    monkeypatch.setattr(log, "warning", warning)
    model = model_text(UNSUPPORTED_VALIDATION_PLAN)
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(course_request(), model)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    assert not transient(caught.value) and len(model.calls) == 1
    warning.assert_called_once_with("Module output rejected module=%s stage=%s rule=%s",
        "POSITIONING", "statement_semantics_invalid", "numerical_support_required")
    assert UNSUPPORTED_VALIDATION_PLAN not in str(warning.call_args)
    assert UNSUPPORTED_VALIDATION_PLAN not in str(caught.value)


@pytest.mark.parametrize("text", [
    "Набрать 5–10 участников.", "Масштабировать, если завершат >50% участников.",
    "Выделить бюджет 1000 рублей.", "Завершить проверку за 14 дней.",
    "1) Проверить спрос. 2) Сравнить ответы.", "Набрать ٥ участников.",
])
@pytest.mark.parametrize("kind", ["HYPOTHESIS", "RECOMMENDATION", "OBSERVATION"])
def test_unsupplied_numerical_assertions_are_rejected_for_every_kind(text, kind):
    model = model_text(text, kind=kind)
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(course_request(), model)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    assert len(model.calls) == 1


@pytest.mark.parametrize("output", ["offer", "validation_plan."])
def test_exact_supplied_numeric_product_truth_is_allowed(output):
    model = model_text(COURSE_TRUTH, cited_local={"product_truth"})
    result = dispatch(course_request(output), model)
    assert result.payload["outputs"][0]["text"] == COURSE_TRUTH
    assert result.normalized_result.claims[0].value == COURSE_TRUTH
    assert result.schema_version == "positioning.payload.v1" and len(model.calls) == 1


def test_exact_numeric_statement_from_cited_accepted_parent_is_allowed():
    parent = dispatch(course_request(identity="positioning.numeric-parent"), model_text(COURSE_TRUTH))
    upstream = UpstreamExecutionResult(producer_node_id="accepted_positioning", result=parent)
    model = model_text(COURSE_TRUTH, cited_local=set(), use_parents=True)
    result = dispatch(course_request(upstream=(upstream,), identity="positioning.numeric-child"), model)
    statement = result.payload["outputs"][0]
    assert statement["text"] == COURSE_TRUTH and not statement["evidence_ids"]
    assert statement["parent_claim_ids"] == (parent.normalized_result.claims[0].claim_id,)
    assert len(model.calls) == 1


def test_uncited_numeric_fact_does_not_authorize_a_numeric_output():
    model = model_text(COURSE_TRUTH, cited_local={"product"})
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(course_request(), model)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    assert len(model.calls) == 1


@pytest.mark.parametrize("text", [
    "Курс длится 6 недель, поэтому продажи вырастут.",
    "Курс длится 12 недель и включает практические задания.",
])
def test_supplied_number_does_not_authorize_new_rationale_or_calculation(text):
    model = model_text(text, cited_local={"product_truth"})
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(course_request(), model)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


def test_independent_numeric_sources_cannot_be_assembled_into_a_new_assertion():
    invocation = course_request()
    invocation = replace(invocation, context_packet=replace(invocation.context_packet,
        known_facts=(*invocation.context_packet.known_facts, fact("existing_proof", "Урок длится 30 минут."))))
    model = model_text("Курс длится 6 недель, урок длится 30 минут.", cited_local={"product_truth", "existing_proof"})
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(invocation, model)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID


def test_qualitative_recommendation_without_numeric_support_remains_allowed():
    text = "Провести пробный разбор и собрать отзывы о формате обратной связи."
    result = dispatch(course_request(), model_text(text))
    assert result.payload["outputs"][0]["text"] == text


@pytest.mark.parametrize("output,kind,rule", [
    ("JTBD_frame", "INFERENCE", SemanticRule.MISSING_SEED_REQUIRES_HYPOTHESIS),
    ("USP_directions", "RECOMMENDATION", SemanticRule.DIFFERENTIATION_REQUIRES_HYPOTHESIS),
    ("offer", "RECOMMENDATION", SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH),
])
def test_existing_semantics_keep_precedence_over_numeric_error(output, kind, rule):
    statement = OutputStatement.model_construct(output_name=output, text="Invented 10 customers",
        kind=kind, confidence="MEDIUM", evidence_ids=[], parent_claim_ids=[])
    with pytest.raises(StatementSemanticsError) as caught:
        PositioningExecutor(model_call=None).validate_statement(statement, {}, {})
    assert caught.value.rule is rule
