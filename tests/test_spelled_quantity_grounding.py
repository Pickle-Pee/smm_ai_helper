"""Cardinal quantities in words share the existing exact-support boundary."""
from types import SimpleNamespace
from dataclasses import replace
import json
from copy import deepcopy

from jsonschema import Draft202012Validator

import pytest

from app.module_execution.executors import PositioningExecutor, ExecutorOutputError
from app.module_execution.executors.common import (StatementSemanticsError, SemanticRule,
    NumericLocation, NumericContextFailureReason, OutputFailureStage)
from app.module_execution.executors.intelligence_common import require_supported_numbers
from app.module_execution.executors.numeric_quantity import has_numeric_quantity
from app.module_execution.executors.numeric_grounding import (
    context_units, numeric_quote_catalog, validate_numeric_context, parent_context_units,
    MAX_NUMERIC_QUOTE_CATALOG_ENTRIES, MAX_NUMERIC_QUOTE_CATALOG_BYTES,
)
from app.module_execution.executors.claim_support import assertion_support
from app.module_execution.executors.intelligence_schemas import OtherStrategyStatement
from app.module_execution.executors.schemas import OutputStatement
from app.module_registry import ModuleId
from app.module_execution import UpstreamExecutionResult
from app.module_execution.executors.provider_schema import nodes
from app.module_execution.executors.cmo_provider_contract import cmo_provider_schema
from tests.test_strategy_intelligence import IntelligenceModel, valid_request, run
from tests.test_module_executors import fact, request, FakeModel, dispatch
from tests.test_cmo_provider_contract import capture, output


@pytest.mark.parametrize("text", [
    "Новичок может за один визит попробовать материал и уйти с готовым изделием.",
    "A beginner can try the material in one visit and leave with a finished item.",
])
def test_unsupplied_single_visit_promise_requires_exact_support(text):
    statement = OutputStatement(output_name="value_proposition", text=text, kind="HYPOTHESIS",
        confidence="MEDIUM", evidence_ids=["evd_truth"], parent_claim_ids=[])
    local = {"evd_truth": SimpleNamespace(input_key="product_truth", value="Collect the item after firing.")}
    with pytest.raises(StatementSemanticsError) as caught:
        PositioningExecutor(model_call=None).validate_statement(statement, local, {})
    assert caught.value.rule is SemanticRule.NUMERICAL_SUPPORT_REQUIRED


@pytest.mark.parametrize("field,value", [
    ("intervention", "Клиент отвечает на две короткие вопросы."),
    ("intervention", "The customer answers two short questions."),
    ("minimum_required_inputs", ["Форма с двумя короткими вопросами."]),
])
def test_unsupplied_design_quantities_in_words_are_rejected(field, value):
    model = IntelligenceModel(use_parents=True)
    with pytest.raises(ExecutorOutputError):
        run(valid_request(ModuleId.EXPERIMENTS), lambda p,d: p["experiments"][0].update({field:value}), model=model)
    assert len(model.calls) == 1


@pytest.mark.parametrize("text", [
    "One visit is sufficient.", "A SINGLE visit is sufficient.", "Достаточно одного визита.",
    "Клиент отвечает на две короткие вопросы.", "Форма с двумя короткими вопросами.",
    "Ask two short additional questions.", "Ask twenty-one questions.",
    "Пригласить два–три новых платных клиента.", "Собрать пять–десять участников.",
    "Через три недели проверить спрос.", "The target is zero dollars.",
    "One hundred visits.", "Сто новых клиентов.", "Two-question form.",
    "Use ٥ questions.", "Use ２ questions.", "Use 3 questions.",
])
def test_detector_recognizes_explicit_counts_and_preserves_unicode_digits(text):
    assert has_numeric_quantity(text)


@pytest.mark.parametrize("text", [
    "One of the questions is unclear.", "Choose one-of-the-visits as context.",
    "Один из вопросов требует уточнения.", "Одна из гипотез требует проверки.",
    "First customers need onboarding.", "Первые клиенты помогут проверить спрос.",
    "Сначала проверить спрос.", "Однако нужно проверить спрос.",
    "Someone visits the workshop.", "One should visit the workshop.",
    "One. Questions follow in another sentence.", "One; visit after confirmation.",
    "Ask qualitative questions and compare replies.", "С одной стороны это гипотеза.",
    "A single source of truth guides messaging.", "One clear message is useful.",
    "Two short new paid questions.",  # Three modifiers exceed the explicit bound.
    "Two very short questions.",     # Unlisted adverb is not inferred as an adjective.
])
def test_detector_avoids_idioms_ordinals_pronouns_and_cross_sentence_matching(text):
    assert not has_numeric_quantity(text)
    require_supported_numbers(text, ())


@pytest.mark.parametrize("text", ["Two short questions are required.", "Нужны два коротких вопроса."])
def test_full_supplied_word_quantity_passes_but_uncited_or_new_rationale_does_not(text):
    require_supported_numbers(text, (text,))
    for candidate, supports in ((text, ("A different assertion.",)),
                                (text + " This guarantees higher conversion.", (text,))):
        with pytest.raises(StatementSemanticsError) as caught:
            require_supported_numbers(candidate, supports)
        assert caught.value.rule is SemanticRule.NUMERICAL_SUPPORT_REQUIRED
    with pytest.raises(StatementSemanticsError):
        require_supported_numbers("Two questions and three visits are required.",
            ("Two questions are required.", "Three visits are required."))


def test_positioning_exact_word_quantity_uses_actual_cited_source():
    source = "The service requires one visit and collection after processing."
    invocation = request(ModuleId.POSITIONING, outputs=("value_proposition",))
    invocation = replace(invocation, context_packet=replace(invocation.context_packet,
        known_facts=tuple(replace(f, value=source) if f.label == "product_truth" else f
                          for f in invocation.context_packet.known_facts)))
    def model_for(cited_key):
        def choose(payload, data):
            selected = next(e for e in data["local_evidence"] if e["input_key"] == cited_key)
            payload["outputs"][0].update(text=source, evidence_ids=[selected["evidence_id"]])
        return FakeModel(choose)
    assert dispatch(invocation, model_for("product_truth")).payload["outputs"][0]["text"] == source
    uncited = replace(invocation, context_packet=replace(invocation.context_packet,
        known_facts=(*tuple(replace(f, value="Guided practice is included.") if f.label == "product_truth" else f
                           for f in invocation.context_packet.known_facts), fact("existing_proof", source))))
    with pytest.raises(ExecutorOutputError) as caught:
        dispatch(uncited, model_for("product_truth"))
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    # Product floor remains before the numerical support check.
    with pytest.raises(ExecutorOutputError):
        dispatch(invocation, model_for("product"))
    def unrelated(payload, data):
        selected = next(e for e in data["local_evidence"] if e["input_key"] == "product_truth")
        payload["outputs"][0].update(text="The service requires two visits.", evidence_ids=[selected["evidence_id"]])
    with pytest.raises(ExecutorOutputError):
        dispatch(invocation, FakeModel(unrelated))


def test_design_full_word_quantity_quote_from_actual_strategic_parent_passes():
    invocation = valid_request(ModuleId.EXPERIMENTS)
    quote = "Ask two short questions."
    parent_request = request(ModuleId.POSITIONING, outputs=("differentiation",))
    parent_request = replace(parent_request, context_packet=replace(parent_request.context_packet,
        known_facts=tuple(replace(f, value=quote) if f.label == "product_truth" else f
                          for f in parent_request.context_packet.known_facts)))
    parent = dispatch(parent_request, FakeModel(lambda p,d: p["outputs"][0].update(text=quote)))
    invocation = replace(invocation, upstream_results=(
        UpstreamExecutionResult(producer_node_id="positioning", result=parent),))
    result = run(invocation, lambda p,d: p["experiments"][0].update(intervention=quote))
    assert result.payload["experiments"][0]["intervention"] == quote


def test_word_quantity_context_retains_complete_units_and_separates_assertion_authority():
    quote = "Ask two short questions, subject to consent."
    assert tuple(context_units(quote)) == (quote,)
    assert not tuple(context_units("two"))
    assert not tuple(context_units(quote + " "))
    assert not tuple(context_units(2))
    stored = json.dumps({"summary": "Ask two questions.", "items": ["Compare responses.", "Use three visits."],
        "numeric_context": [{"support_id":"evd_original", "quote":quote}]})
    assert assertion_support(stored) == ("Compare responses.",)
    assert quote in tuple(parent_context_units(stored))
    assert assertion_support(quote) == (quote,)  # Plain accepted assertion authority is unchanged.
    with pytest.raises(StatementSemanticsError):
        require_supported_numbers(quote, assertion_support(stored))


@pytest.mark.parametrize("field", ["text", "items"])
def test_cmo_word_quantity_prose_stays_forbidden_even_when_source_supported(field):
    quote = "Ask two short questions."
    values = dict(output_name="strategic_diagnosis", text="Validate demand", items=["Compare responses"],
        kind="HYPOTHESIS", confidence="MEDIUM", evidence_ids=["evd_source"], parent_claim_ids=[], numeric_context=[])
    values[field] = quote if field == "text" else [quote]
    statement = OtherStrategyStatement(**values)
    with pytest.raises(StatementSemanticsError) as caught:
        validate_numeric_context(statement, {"evd_source":SimpleNamespace(value=quote)}, {})
    assert caught.value.numeric_location is (NumericLocation.TEXT if field == "text" else NumericLocation.ITEMS)


def test_cmo_word_quote_catalog_and_provider_keep_exact_same_source_pairs():
    quote = "Ask two short questions, subject to consent."
    other = "The service takes one visit, with later collection."
    invocation = request(ModuleId.VIRTUAL_CMO, facts=(fact("business_goal", "Validate demand"),
        fact("product", "A service"), fact("product_truth", quote), fact("existing_proof", other)))
    _, canonical, provider, ids = capture(invocation)
    original = deepcopy(canonical)
    validator = Draft202012Validator(provider)
    candidate = output(ids, numeric_context=[{"support_id":ids["product_truth"], "quote":quote}])
    assert validator.is_valid(candidate)
    local = {ids["product_truth"]:SimpleNamespace(value=quote), ids["existing_proof"]:SimpleNamespace(value=other)}
    statement = OtherStrategyStatement(**{**candidate["outputs"][0], "output_name":"strategic_diagnosis"})
    validate_numeric_context(statement, local, {})
    assert numeric_quote_catalog(local, {}) == sorted(numeric_quote_catalog(local, {}), key=lambda e:e["support_id"])
    assert cmo_provider_schema(canonical, numeric_quote_catalog(local, {})) == provider
    assert canonical == original
    assert all(node.get("pattern") == "^[^0-9]*$" for node in nodes(provider) if "pattern" in node)
    for bad in ({"support_id":ids["existing_proof"], "quote":quote},
                {"support_id":ids["product_truth"], "quote":"Ask two short questions"},
                {"support_id":"evd_unknown", "quote":quote}):
        mutated = deepcopy(candidate)
        mutated["outputs"][0]["numeric_context"] = [bad]
        assert not validator.is_valid(mutated)


@pytest.mark.parametrize("mutation,reason", [
    ("uncited", NumericContextFailureReason.SUPPORT_NOT_CITED),
    ("cross_pair", NumericContextFailureReason.QUOTE_NOT_EXACT),
    ("fragment", NumericContextFailureReason.QUOTE_IS_FRAGMENT),
    ("unknown", NumericContextFailureReason.SUPPORT_NOT_FOUND),
])
def test_original_cmo_guard_rejects_wrong_word_quote_identity_and_fragments(mutation, reason):
    quote = "Ask two short questions, subject to consent."
    local = {"evd_source":SimpleNamespace(value=quote),
             "evd_other":SimpleNamespace(value="The service takes one visit.")}
    identity, text = "evd_source", quote
    if mutation == "cross_pair": identity = "evd_other"
    if mutation == "fragment": text = "Ask two short questions"
    if mutation == "unknown": identity = "evd_unknown"
    statement = OtherStrategyStatement(output_name="strategic_diagnosis", text="Validate demand", items=["Compare responses"],
        kind="HYPOTHESIS", confidence="MEDIUM", evidence_ids=["evd_other"] if mutation == "uncited" else list(local),
        parent_claim_ids=[], numeric_context=[{"support_id":identity, "quote":text}])
    with pytest.raises(StatementSemanticsError) as caught:
        validate_numeric_context(statement, local, {})
    assert caught.value.numeric_context_reason is reason


def test_word_quote_catalog_caps_and_whole_leaf_extraction_remain_bounded():
    local = {f"evd_{i:03}":SimpleNamespace(value="Two questions are required. " + "qualifier " * 90 + chr(65+i%26))
             for i in range(100)}
    catalog = numeric_quote_catalog(local, {})
    assert 0 < len(catalog) <= MAX_NUMERIC_QUOTE_CATALOG_ENTRIES
    assert len(json.dumps(catalog, ensure_ascii=False).encode()) <= MAX_NUMERIC_QUOTE_CATALOG_BYTES
    assert all(row["exact_quote"] == local[row["support_id"]].value for row in catalog)
    assert not tuple(context_units("Two questions. " + "x" * 1000))


def test_provider_guidance_words_and_fulfillment_do_not_claim_deterministic_entailment():
    from app.module_execution.executors.experiments import ExperimentsExecutor
    from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
    for executor in (PositioningExecutor, ExperimentsExecutor, VirtualCMOExecutor):
        assert "Quantities written as words are numbers too" in executor.instruction
    assert "Preserve supplied fulfillment conditions" in PositioningExecutor.instruction
    assert "New operational promises require owner" in PositioningExecutor.instruction



def test_actual_accepted_cmo_word_context_cannot_authorize_experiment_assertion():
    quote = "Ask two short questions, subject to consent."
    invocation = valid_request(ModuleId.VIRTUAL_CMO)
    invocation = replace(invocation, context_packet=replace(invocation.context_packet,
        known_facts=(*invocation.context_packet.known_facts, fact("existing_proof", quote))))
    def supplied_context(payload, data):
        identity = next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"] == "existing_proof")
        assert identity in payload["outputs"][0]["evidence_ids"]
        payload["outputs"][0]["numeric_context"] = [{"support_id":identity, "quote":quote}]
    parent = run(invocation, supplied_context)
    assert parent.payload["outputs"][0]["numeric_context"][0]["quote"] == quote
    experiment_request = request(ModuleId.EXPERIMENTS, facts=(), upstream=(
        UpstreamExecutionResult(producer_node_id="virtual_cmo", result=parent),))
    model = IntelligenceModel(use_parents=True)
    with pytest.raises(ExecutorOutputError) as caught:
        run(experiment_request, lambda p,d: p["experiments"][0].update(intervention=quote), model=model)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    assert len(model.calls) == 1
