"""Russian daycare regression: recommendations never inherit numerical entailment."""
from dataclasses import replace
import json
import traceback

import pytest
from jsonschema import Draft202012Validator

from app.module_execution.executors.common import (
    ExecutorOutputError, NumericLocation, OutputFailureStage, StatementSemanticsError,
    first_party_evidence, scoped_facts,
)
from app.module_execution.executors.intelligence_common import require_supported_numbers
from app.module_execution.executors.intelligence_schemas import OtherStrategyStatement, StrategyOutput
from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
from app.module_execution.executors.support_schema import support_response_schema
from app.module_registry import ModuleId
from app.orchestration_runtime.serialization import result_from_json, result_to_json
from tests.test_module_executors import fact, request
from tests.test_strategy_intelligence import IntelligenceModel, positioning, run, upstream


AGE = "Детский сад принимает детей от 2 до 7 лет."
PRICE = "Полный день стоит 30 000 рублей в месяц; неполный день — 18 000 рублей."
GOAL = "Цель владельца — повысить прибыльность, сохранив качество ухода."
RECOMMENDATION = "Сосредоточить привлечение на семьях с детьми от 2 до 7 лет при цене 30 000 рублей."


@pytest.fixture(autouse=True)
def enable_module_log(monkeypatch):
    # Other migration tests may disable existing application loggers via Alembic
    # fileConfig. Isolate emission assertions from that unrelated global state.
    from app.module_execution.executors.common import log
    monkeypatch.setattr(log, "disabled", False)


def daycare_facts():
    return (fact("business_goal", GOAL), fact("product", "Частный детский сад"),
            fact("target_or_target_hypothesis", AGE),
            fact("product_truth", {"pricing": PRICE, "capacity": 30}),
            fact("site_claim", "На сайте заявлены группы до 12 детей; это не подтверждено владельцем."))


def daycare_request():
    return request(ModuleId.VIRTUAL_CMO, facts=daycare_facts(), upstream=upstream(positioning()))


def grounded_output(raw, data):
    statement = raw["outputs"][0]
    statement.update(text="Проверить спрос на форматы посещения без предположений о рентабельности.",
                     items=["Сопоставить потребности семей с подтверждёнными форматами посещения."])
    by_key = {e["input_key"]: e for e in data["local_evidence"]}
    refs = [(by_key["target_or_target_hypothesis"]["evidence_id"], AGE),
            (by_key["product_truth"]["evidence_id"], PRICE)]
    statement["evidence_ids"] = [identity for identity, _ in refs]
    statement["numeric_context"] = [dict(support_id=identity, quote=quote) for identity, quote in refs]


@pytest.mark.parametrize("field", ["text", "items"])
def test_production_shaped_original_mismatch_and_bounded_field_diagnostic(field, caplog):
    # Original whole-string rule rejects legitimate context embedded in strategy.
    with pytest.raises(StatementSemanticsError):
        require_supported_numbers(RECOMMENDATION, [AGE, PRICE])
    model = IntelligenceModel(use_parents=True)
    def legacy(raw, _):
        raw["outputs"][0][field] = RECOMMENDATION if field == "text" else [RECOMMENDATION]
    with pytest.raises(ExecutorOutputError) as caught:
        run(daycare_request(), legacy, model=model)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    assert "rule=numerical_support_required field=" + field in caplog.text
    assert RECOMMENDATION not in caplog.text + "".join(traceback.format_exception(caught.value))
    assert len(model.calls) == 1


def test_supported_context_is_gated_persisted_and_presented_as_quotes():
    model = IntelligenceModel(use_parents=True)
    result = run(daycare_request(), grounded_output, model=model)
    from app.marketing_orchestrator.quality_gates import QualityGateEvaluator
    from app.marketing_orchestrator.quality_gates.contracts import EvaluationBatch
    from app.module_execution.acceptance import fully_accepted
    manifest = QualityGateEvaluator().evaluate(EvaluationBatch(batch_id="bat_numeric",
        results=tuple(u.result.normalized_result for u in daycare_request().upstream_results)
                + (result.normalized_result,))).synthesis_manifest
    assert fully_accepted(result, manifest.accepted_result_ids, manifest.accepted_claim_ids)
    assert result == result_from_json(result_to_json(result))
    claim = json.loads(result.normalized_result.claims[0].value)
    assert [c["quote"] for c in claim["numeric_context"]] == [AGE, PRICE]
    assert result.payload["outputs"][0]["numeric_context"]
    assert any("Economics absent" in l.description for l in result.normalized_result.limitations)
    assert len(model.calls) == 1
    schema = model.calls[0]["response_schema"]
    assert "numeric_context" in schema["$defs"]["OtherStrategyStatement"]["required"]
    from app.marketing_copilot.presentation import module_presentation
    presented = module_presentation(result)
    assert AGE in presented.strategic_diagnosis.numeric_context[0]
    assert "не подтверждение вывода" in presented.strategic_diagnosis.numeric_context[0]
    from bot import copilot_contracts as dto, copilot_rendering as rendering
    telegram = dto.RunResponse(run_id="a" * 32, status=dto.RunStatus.COMPLETED,
        strategy=dto.Strategy.model_validate(presented.model_dump()))
    rendered = "\n".join(rendering.run(telegram))
    assert AGE in rendered and PRICE in rendered
    assert "evd_" not in rendered and "clm_" not in rendered


@pytest.mark.parametrize("quote", [
    "Цена 31 000 рублей в месяц.",                         # invented number
    "Прибыль увеличится на 30 000 рублей.",                 # same number, different assertion
    "Цель — увеличить прибыль на 30%.",                    # invented target
    "Выручка составит 900 000 рублей в месяц.",             # capacity * price
    "Для детей от 2 до 7 лет цена 18 000 рублей.",           # unsupported combination
    "Полный день стоит 30 000 рублей в месяц",               # substring drops qualification
    "30 000",                                               # bare token overlap
    PRICE.replace("30 000", "30000"),                      # no semantic normalization
    "На сайте заявлены группы до 12 детей.",                 # qualifier removed
])
def test_unsupported_numeric_assertions_fail_with_one_call(quote, caplog):
    model = IntelligenceModel(use_parents=True)
    def invalid(raw, data):
        grounded_output(raw, data)
        raw["outputs"][0]["numeric_context"][1]["quote"] = quote
    with pytest.raises(ExecutorOutputError) as caught:
        run(daycare_request(), invalid, model=model)
    assert caught.value.stage is OutputFailureStage.STATEMENT_SEMANTICS_INVALID
    assert "field=numeric_context" in caplog.text
    assert quote not in caplog.text
    assert len(model.calls) == 1


@pytest.mark.parametrize("mutation", ["uncited", "wrong_source", "unknown"])
def test_exact_quote_requires_its_own_cited_identity(mutation):
    def invalid(raw, data):
        grounded_output(raw, data)
        statement = raw["outputs"][0]
        quote = statement["numeric_context"][1]
        if mutation == "uncited":
            statement["evidence_ids"].remove(quote["support_id"])
        else:
            quote["support_id"] = statement["evidence_ids"][0] if mutation == "wrong_source" else "evd_invented"
    with pytest.raises(ExecutorOutputError) as caught:
        run(daycare_request(), invalid)
    assert caught.value.stage is (OutputFailureStage.SCHEMA_INVALID if mutation == "unknown"
                                 else OutputFailureStage.STATEMENT_SEMANTICS_INVALID)


def test_accepted_parent_full_assertion_and_site_qualification_are_preserved():
    parent = positioning()
    parent = replace(parent, payload=result_to_json(parent)["payload"], normalized_result=replace(parent.normalized_result,
        claims=(replace(parent.normalized_result.claims[0], value="Гипотеза: семьи с детьми от 2 до 7 лет оценят гибкий график."),)))
    req = request(ModuleId.VIRTUAL_CMO, facts=daycare_facts(), upstream=upstream(parent))
    def supplied(raw, data):
        statement = raw["outputs"][0]
        eid = next(e["evidence_id"] for e in data["local_evidence"] if e["input_key"] == "site_claim")
        statement["evidence_ids"] = [eid]
        statement["numeric_context"] = [dict(support_id=parent.normalized_result.claims[0].claim_id,
            quote=parent.normalized_result.claims[0].value), dict(support_id=eid, quote=daycare_facts()[-1].value)]
    result = run(req, supplied)
    quotes = json.loads(result.normalized_result.claims[0].value)["numeric_context"]
    assert quotes[0]["quote"].startswith("Гипотеза:")
    assert "не подтверждено" in quotes[1]["quote"]


def test_supplied_numeric_profitability_goal_remains_a_goal_not_a_projection():
    goal = "Цель владельца — достичь рентабельности 20%; это цель, а не прогноз."
    req = request(ModuleId.VIRTUAL_CMO, facts=(fact("business_goal", goal), *daycare_facts()[1:]))
    def supplied(raw, data):
        statement = raw["outputs"][0]
        identity = data["local_evidence"][0]["evidence_id"]
        statement["evidence_ids"] = [identity]
        statement["numeric_context"] = [dict(support_id=identity, quote=goal)]
    result = run(req, supplied, model=IntelligenceModel())
    assert result.payload["outputs"][0]["numeric_context"][0]["quote"] == goal
    def projected(raw, data):
        supplied(raw, data)
        raw["outputs"][0]["text"] = "Предложенная стратегия обеспечит рентабельность 20%."
    with pytest.raises(ExecutorOutputError):
        run(req, projected, model=IntelligenceModel())


def test_structured_accepted_cmo_parent_propagates_quotes_without_internal_json():
    parent = run(daycare_request(), grounded_output)
    req = request(ModuleId.VIRTUAL_CMO, identity="cmo.child:2", facts=daycare_facts(), upstream=upstream(parent))
    claim = parent.normalized_result.claims[0]
    def inherited(raw, _):
        raw["outputs"][0]["numeric_context"] = [dict(support_id=claim.claim_id, quote=PRICE)]
    result = run(req, inherited)
    assert result.payload["outputs"][0]["numeric_context"][0]["quote"] == PRICE
    def internal_json(raw, _):
        raw["outputs"][0]["numeric_context"] = [dict(support_id=claim.claim_id, quote=claim.value)]
    with pytest.raises(ExecutorOutputError):
        run(req, internal_json)
    from app.module_execution.executors.numeric_grounding import parent_context_units
    assert list(parent_context_units('{"related_claim_id":"clm_internal123"}')) == []
    assert list(parent_context_units('{"related_claim_id":"clm_internal123"')) == []


def test_runtime_bypass_cannot_introduce_numeric_assertions_or_partial_quotes():
    req = daycare_request()
    evidence = first_party_evidence(req, scoped_facts(req))
    local = {e.record.evidence_id: e for e in evidence}
    eid = evidence[3].record.evidence_id
    statement = OtherStrategyStatement.model_construct(output_name="strategic_diagnosis",
        text="Качественная рекомендация", items=["Проверить спрос"], kind="HYPOTHESIS", confidence="MEDIUM",
        evidence_ids=[eid], parent_claim_ids=[], numeric_context=[])
    for field, location, value in [("text", NumericLocation.TEXT, PRICE),
                                  ("items", NumericLocation.ITEMS, [PRICE])]:
        baseline = getattr(statement, field)
        setattr(statement, field, value)
        with pytest.raises(StatementSemanticsError) as caught:
            VirtualCMOExecutor(model_call=None).validate_statement(statement, local, {})
        assert caught.value.numeric_location is location
        setattr(statement, field, baseline)
    from app.module_execution.executors.intelligence_schemas import NumericContext
    statement.numeric_context = [NumericContext(support_id=eid, quote="30 000 рублей")]
    with pytest.raises(StatementSemanticsError) as caught:
        VirtualCMOExecutor(model_call=None).validate_statement(statement, local, {})
    assert caught.value.numeric_location is NumericLocation.CONTEXT


def test_scalar_numbers_do_not_supply_assertions_and_old_payloads_remain_readable():
    from app.module_execution.executors.numeric_grounding import context_units
    assert list(context_units({"price": 30000, "age": "2", "capacity": "30"})) == []
    assert list(context_units({"pricing": PRICE})) == [PRICE]
    assert list(context_units(PRICE + " " * 1000)) == []
    payload = dict(outputs=[dict(output_name="strategic_diagnosis", kind="HYPOTHESIS",
        confidence="MEDIUM", text="Качественный вывод", items=["Проверить"], evidence_ids=["evd_local"],
        parent_claim_ids=[])], assumptions=[], limitations=[])
    assert StrategyOutput.model_validate(payload).outputs[0].numeric_context == []
    schema = support_response_schema(StrategyOutput, ["evd_local"], [])
    assert not Draft202012Validator(schema).is_valid(payload)
