"""Reasons to believe quote actual cited product proof, not invented promises."""
from types import SimpleNamespace

import pytest

from app.module_execution.executors.positioning import PositioningExecutor
from app.module_execution.executors.schemas import OutputStatement
from app.module_execution.executors.common import StatementSemanticsError, SemanticRule


def statement(text, *, refs=("evd_product",), parents=(), kind="INFERENCE", output="RTB"):
    return OutputStatement(output_name=output, text=text, kind=kind, confidence="MEDIUM",
        evidence_ids=list(refs), parent_claim_ids=list(parents))


def local():
    return {"evd_product": SimpleNamespace(input_key="product_truth", value=
        "Занятия с мастером; материалы и обжиг включены; готовое изделие клиент забирает после обжига.")}


@pytest.mark.parametrize("text", [
    "Материалы и обжиг включены — это прямое доказательство опыта без дополнительных действий со стороны ученика.",
    "Всё включено, поэтому ученику не нужно ничего делать дополнительно.",
    "Included materials and firing prove that no further customer actions are needed.",
])
def test_product_source_presence_does_not_authorize_an_invented_reason_to_believe(text):
    with pytest.raises(StatementSemanticsError) as caught:
        PositioningExecutor(model_call=None).validate_statement(statement(text), local(), {})
    assert caught.value.rule is SemanticRule.RTB_QUOTE_REQUIRED


@pytest.mark.parametrize("kind", ["OBSERVATION", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION"])
def test_exact_supplied_substantiation_retains_canonical_kinds_and_source_conditions(kind):
    sources = local()
    text = sources["evd_product"].value
    PositioningExecutor(model_call=None).validate_statement(statement(text, kind=kind), sources, {})


@pytest.mark.parametrize("category", ["product_truth", "existing_proof"])
def test_rtb_requires_its_own_actually_cited_product_proof(category):
    sources = local()
    sources["evd_other"] = SimpleNamespace(input_key=category, value="Пользователи подтвердили формат выдачи.")
    executor = PositioningExecutor(model_call=None)
    text = sources["evd_other"].value
    with pytest.raises(StatementSemanticsError) as caught:
        executor.validate_statement(statement(text), sources, {})
    assert caught.value.rule is SemanticRule.RTB_QUOTE_REQUIRED
    executor.validate_statement(statement(text, refs=("evd_other",)), sources, {})


def test_other_cited_context_and_parent_cannot_launder_a_product_promise():
    sources = local()
    text = "Больше действий не потребуется."
    sources["evd_message"] = SimpleNamespace(input_key="message", value=text)
    parents = {"clm_parent": SimpleNamespace(value=text)}
    with pytest.raises(StatementSemanticsError) as caught:
        PositioningExecutor(model_call=None).validate_statement(
            statement(text, refs=("evd_product", "evd_message"), parents=("clm_parent",)), sources, parents)
    assert caught.value.rule is SemanticRule.RTB_QUOTE_REQUIRED


def test_product_source_floor_and_numeric_rules_keep_precedence():
    executor = PositioningExecutor(model_call=None)
    sources = local()
    sources["evd_message"] = SimpleNamespace(input_key="message", value="Owner context")
    for value,rule in ((statement("A promise", refs=("evd_message",)), SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH),
                       (statement("Four visits in 7 days"), SemanticRule.NUMERICAL_SUPPORT_REQUIRED)):
        with pytest.raises(StatementSemanticsError) as caught:
            executor.validate_statement(value, sources, {})
        assert caught.value.rule is rule


def test_other_qualitative_strategy_outputs_keep_their_existing_reasoning_contract():
    PositioningExecutor(model_call=None).validate_statement(
        statement("Test a local message-led offer.", output="offer", kind="RECOMMENDATION"), local(), {})


def test_old_canonical_payload_is_readable_without_retroactive_repair():
    from app.module_execution.executors.schemas import PositioningOutput
    old = {"outputs": [statement("A legacy unverified inference.").model_dump()], "assumptions": [], "limitations": []}
    parsed = PositioningOutput.model_validate(old)
    assert parsed.model_dump() == old


@pytest.mark.parametrize("text", ["Материалы плюс обжиг входят в занятие.",
    "Готовое изделие можно получить после обжига.", "Занятия ведёт специалист."])
def test_rtb_paraphrases_do_not_bypass_the_literal_proof_boundary(text):
    with pytest.raises(StatementSemanticsError) as caught:
        PositioningExecutor(model_call=None).validate_statement(statement(text), local(), {})
    assert caught.value.rule is SemanticRule.RTB_QUOTE_REQUIRED


def test_structured_proof_uses_existing_literal_representation_and_is_not_mutated():
    import json
    from copy import deepcopy
    sources = {"evd_product": SimpleNamespace(input_key="product_truth", value={"format": "Materials and firing included"})}
    before = deepcopy(sources["evd_product"].value)
    value = statement(json.dumps(before, ensure_ascii=False))
    original = value.model_dump()
    PositioningExecutor(model_call=None).validate_statement(value, sources, {})
    assert value.model_dump() == original and sources["evd_product"].value == before
