"""Request-specific positioning choices retain source scope through review."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.module_execution.executors import PositioningExecutor
from app.module_execution.executors.positioning_strategy import build_strategy_choices
from app.module_registry import ModuleId
from app.orchestration_runtime.claim_verification import review_positioning, verification_inputs
from tests.test_module_executors import fact, request
from tests.test_positioning_support_selection import SelectionModel, qualitative, sourced


COURSE = (
    "Курс ФотоСтарт длится 6 недель. Участники выполняют практические задания "
    "и получают письменную обратную связь. Для занятий не требуется профессиональное оборудование."
)
CERAMICS = "Материалы и обжиг включены. Участники забирают изделия после обжига в другой день."
CASES = {
    "course": ("Курс мобильной фотографии ФотоСтарт", COURSE),
    "ceramics": ("Мастер-класс керамики Глина", CERAMICS),
}


def invocation(case):
    product, truth = CASES[case]
    return request(ModuleId.POSITIONING, facts=(
        fact("product", product), fact("target_or_target_hypothesis", "Начинающие взрослые"),
        fact("product_truth", truth),
        fact("existing_proof", "В демонстрационном примере используют гончарный круг."),
    ))


def output(text, ids, *, name="value_proposition"):
    return {"output_name": name, "text": text, "evidence_ids": list(ids), "parent_claim_ids": []}


def dynamic_choice(evidence, name="value_proposition"):
    return max(build_strategy_choices(evidence)[name], key=lambda choice: len(choice["required_source_ids"]))


def run_review(rows, evidence, mutate=None):
    captured = {}

    async def auditor(**kwargs):
        data = json.loads(kwargs["text"])
        reviews = {}
        for name, row in data["outputs"].items():
            text = row["spans"]["whole"]
            exact_ids = [identity for identity, source in row["evidence"].items()
                         if source["role"] == "product_truth" and source["text"] == text]
            claims = ([{"span_id": unit["span_id"], "unit_id": identity, "verdict": "CLEAR",
                        "support_ids": unit["evidence_ids"]} for identity, unit in row["units"].items()]
                      if row["units"] else [{"span_id": "whole", "unit_id": "free", "verdict": "CLEAR",
                                            "support_ids": exact_ids}])
            reviews[name] = {"atoms_complete": True, "output_fulfilled": True, "claims": claims}
        report = {"draft_fingerprint": data["draft_fingerprint"], "assessment": "APPROVE", "reviews": reviews}
        if mutate:
            mutate(report, data)
        captured.update(data=data, report=report, schema=kwargs["response_schema"])
        return json.dumps(report, ensure_ascii=False)

    decision = asyncio.run(review_positioning(auditor, SimpleNamespace(payload={"outputs": rows}), evidence))
    return decision, captured


@pytest.mark.parametrize("case", CASES)
def test_dynamic_choice_with_all_dependencies_is_reviewable(case):
    evidence = verification_inputs(invocation(case))
    choice = dynamic_choice(evidence)
    assert len(choice["required_source_ids"]) == 3
    decision, captured = run_review([output(choice["text"], choice["required_source_ids"])], evidence)
    assert decision["status"] == "verified"
    assert choice in captured["data"]["outputs"]["value_proposition"]["strategy_choices"]
    assert set(choice["required_source_ids"]) <= captured["data"]["outputs"]["value_proposition"]["evidence"].keys()


def test_demonstration_cannot_be_an_unrelated_strategic_citation():
    evidence = verification_inputs(invocation("course"))
    evidence["evd_unused_demo"] = {"role": "demonstration", "text": "An example compares photographs."}
    choice = dynamic_choice(evidence)
    decision, _ = run_review([output(choice["text"], (*choice["required_source_ids"], "evd_unused_demo"))], evidence)
    assert decision["status"] == "rejected"
    assert decision["findings"][0]["reason"] == "irrelevant_demonstration_citation"


def test_strategy_context_source_does_not_become_a_factual_target_unit():
    evidence = verification_inputs(invocation("course"))
    truth_id = next(identity for identity, source in evidence.items() if source["role"] == "product_truth")

    def misuse(report, data):
        report["reviews"]["target"]["claims"] = [{"span_id": "whole", "unit_id": "free",
                                                   "verdict": "CLEAR", "support_ids": [truth_id]}]

    ids = tuple(identity for identity, source in evidence.items() if source["role"] != "demonstration")
    decision, captured = run_review([output(evidence[truth_id]["text"], ids, name="target")], evidence, misuse)
    assert captured["data"]["outputs"]["target"]["units"] == {}
    assert decision["status"] in {"rejected", "blocked"}


def test_several_recommendations_inside_a_complete_bound_message_plan_are_reviewable():
    evidence = verification_inputs(invocation("course"))
    choice = dynamic_choice(evidence, "message_hierarchy")

    def separate(report, data):
        report["reviews"]["message_hierarchy"]["claims"] = [
            {"span_id": identity, "unit_id": "free", "verdict": "CLEAR", "support_ids": []}
            for identity in data["outputs"]["message_hierarchy"]["spans"] if identity.startswith("sentence_")
        ]

    decision, _ = run_review([output(choice["text"], choice["required_source_ids"], name="message_hierarchy")], evidence, separate)
    assert decision["status"] == "verified"
    assert len(decision["reviews"][0]["claims"]) > 1


@pytest.mark.parametrize("case", CASES)
def test_counterfactual_risk_check_is_reviewable_but_negative_audit_still_blocks(case):
    evidence = verification_inputs(invocation(case))
    choice = dynamic_choice(evidence, "claim_risks")
    row = output(choice["text"], choice["required_source_ids"], name="claim_risks")
    assert "проверить, не" in choice["text"]

    def recommendation(report, data):
        report["reviews"]["claim_risks"]["claims"][0]["verdict"] = "CLEAR"

    row["kind"] = "RECOMMENDATION"
    decision, _ = run_review([row], evidence, recommendation)
    assert decision["status"] == "verified"

    def uncertain(report, data):
        report["reviews"]["claim_risks"]["claims"][0]["verdict"] = "UNSUPPORTED"

    decision, _ = run_review([row], evidence, uncertain)
    assert decision["assessment"] == "APPROVE"
    assert decision["status"] == "rejected"


@pytest.mark.parametrize("field,value", [("category", "product"), ("category", "audience"),
                                         ("kind", "fact"), ("status", "SUPPORTED")])
def test_auditor_cannot_supply_proof_category_kind_or_status(field, value):
    evidence = verification_inputs(invocation("course"))
    choice = dynamic_choice(evidence)

    def relabel(report, data):
        report["reviews"]["value_proposition"]["claims"][0][field] = value

    decision, _ = run_review([output(choice["text"], choice["required_source_ids"])], evidence, relabel)
    assert decision == {"status": "blocked", "reason": "invalid_claim_review"}


@pytest.mark.parametrize("declared_kind,expected_kind", [("HYPOTHESIS", "hypothesis"), ("RECOMMENDATION", "recommendation")])
def test_clear_verdict_keeps_the_server_owned_declared_proposal_kind(declared_kind, expected_kind):
    evidence = verification_inputs(invocation("course"))
    choice = dynamic_choice(evidence)
    row = {**output(choice["text"], choice["required_source_ids"]), "kind": declared_kind}
    decision, captured = run_review([row], evidence)
    assert decision["status"] == "verified"
    assert captured["data"]["outputs"]["value_proposition"]["declared_kind"] == declared_kind
    assert decision["reviews"][0]["claims"][0]["kind"] == expected_kind
    assert set(captured["report"]["reviews"]["value_proposition"]["claims"][0]) == {
        "span_id", "unit_id", "verdict", "support_ids",
    }


@pytest.mark.parametrize("name", ["demand_context", "JTBD_frame"])
def test_purpose_metadata_allows_hypothetical_working_depth_situation_and_task(name):
    evidence = verification_inputs(invocation("course"))
    choice = dynamic_choice(evidence, name)
    row = {**output(choice["text"], choice["required_source_ids"], name=name), "kind": "HYPOTHESIS"}
    decision, captured = run_review([row], evidence)
    view = captured["data"]["outputs"][name]
    assert view["declared_kind"] == "HYPOTHESIS"
    assert "WORKING" in view["purpose"] and "not required" in view["purpose"]
    assert decision["status"] == "verified"


@pytest.mark.parametrize("verdict", ["UNSUPPORTED", "CONTRADICTED", "UNVERIFIABLE"])
def test_negative_verdict_overrides_an_exact_supported_proposal(verdict):
    evidence = verification_inputs(invocation("course"))
    choice = dynamic_choice(evidence)

    def reject(report, data):
        report["reviews"]["value_proposition"]["claims"][0]["verdict"] = verdict

    decision, _ = run_review([output(choice["text"], choice["required_source_ids"])], evidence, reject)
    if verdict == "UNVERIFIABLE":
        assert decision == {"status": "blocked", "reason": "invalid_claim_review"}
        return
    assert decision["assessment"] == "APPROVE"
    assert decision["status"] == "rejected"
    assert decision["findings"][0]["status"] == verdict


def test_bound_proposal_separates_factual_fidelity_from_empirical_validation():
    evidence = verification_inputs(invocation("course"))
    choice = dynamic_choice(evidence)
    decision, captured = run_review([output(choice["text"], choice["required_source_ids"])], evidence)
    view = captured["data"]["outputs"]["value_proposition"]
    assert view["audit_scope"] == "authorized_prospective_proposal"
    assert decision["empirical_validation"]["value_proposition"] == "REQUIRED"
    schema = captured["schema"]["properties"]["reviews"]["properties"]["value_proposition"]
    assert schema["properties"]["claims"]["items"]["properties"]["verdict"]["enum"] == [
        "CLEAR", "UNSUPPORTED", "CONTRADICTED"]
    assert decision["status"] == "verified"


@pytest.mark.parametrize("veto", ["UNCERTAIN", "atoms_complete", "output_fulfilled"])
def test_bound_proposal_actual_uncertainty_and_usefulness_vetoes_are_preserved(veto):
    evidence = verification_inputs(invocation("course"))
    choice = dynamic_choice(evidence)

    def uncertain(report, data):
        if veto == "UNCERTAIN":
            report["assessment"] = veto
        else:
            report["reviews"]["value_proposition"][veto] = False

    decision, _ = run_review([output(choice["text"], choice["required_source_ids"])], evidence, uncertain)
    assert decision["findings"] == []
    assert decision["status"] == "blocked"


@pytest.mark.parametrize("alteration", ["missing_source", "changed_text", "unsupported_feature"])
def test_prospective_scope_cannot_be_obtained_by_a_producer_label(alteration):
    evidence = verification_inputs(invocation("course"))
    choice = dynamic_choice(evidence)
    text, ids = choice["text"], choice["required_source_ids"]
    if alteration == "missing_source":
        ids = ids[:-1]
    elif alteration == "changed_text":
        text = text[:-1]
    else:
        text = "Hypothesis: the course is accredited."
    row = {**output(text, ids), "kind": "HYPOTHESIS"}
    decision, captured = run_review([row], evidence)
    assert captured["data"]["outputs"]["value_proposition"]["audit_scope"] == "free_prose"
    assert decision["status"] == "rejected"


def test_source_fact_keeps_unverifiable_verdict_and_all_required_units():
    req = invocation("course")
    evidence = verification_inputs(req)
    identity = next(identity for identity, source in evidence.items() if source["role"] == "product_truth")
    text = evidence[identity]["text"]

    def uncertain(report, data):
        report["reviews"]["offer"]["claims"][0]["verdict"] = "UNVERIFIABLE"

    decision, captured = run_review([output(text, [identity], name="offer")], evidence, uncertain)
    assert captured["data"]["outputs"]["offer"]["audit_scope"] == "source_fact"
    assert len(decision["source_unit_coverage"]["offer"]) == 4
    assert decision["status"] == "rejected"
    assert decision["findings"][0]["status"] == "UNVERIFIABLE"


@pytest.mark.parametrize("case", CASES)
def test_missing_dynamic_dependency_cannot_be_approved(case):
    evidence = verification_inputs(invocation(case))
    choice = dynamic_choice(evidence)
    for omitted in choice["required_source_ids"]:
        ids = set(choice["required_source_ids"]) - {omitted}
        decision, captured = run_review([output(choice["text"], ids)], evidence)
        assert decision["status"] == "rejected"
        assert choice not in captured["data"]["outputs"]["value_proposition"]["strategy_choices"]


def test_choice_for_another_output_does_not_fulfill_this_output():
    evidence = verification_inputs(invocation("course"))
    choice = dynamic_choice(evidence, "positioning_statement")
    decision, captured = run_review([output(choice["text"], choice["required_source_ids"], name="category")], evidence)
    assert decision["status"] == "rejected"
    assert choice not in captured["data"]["outputs"]["category"]["strategy_choices"]


def test_static_generic_research_task_cannot_replace_the_category():
    evidence = verification_inputs(invocation("course"))
    decision, _ = run_review([output("Test whether beginners value knowing what to practice next.", (), name="category")], evidence)
    assert decision["status"] == "rejected"


def test_named_output_fulfillment_is_separate_from_complete_atoms_and_coverage():
    evidence = verification_inputs(invocation("ceramics"))
    choice = dynamic_choice(evidence, "positioning_statement")

    def unfulfilled(report, data):
        report["reviews"]["positioning_statement"]["output_fulfilled"] = False

    decision, _ = run_review([output(choice["text"], choice["required_source_ids"], name="positioning_statement")],
                            evidence, unfulfilled)
    assert decision["status"] == "blocked"
    assert decision["coverage"] == "complete"
    assert decision["findings"] == []


@pytest.mark.parametrize("truth", [COURSE, CERAMICS])
def test_demonstration_does_not_enable_owner_feature_angles(truth):
    evidence = {
        "identity": {"text": "Вводное занятие", "role": "product_identity"},
        "audience": {"text": "Взрослые", "role": "audience"},
        "demo": {"text": truth, "role": "demonstration"},
    }
    choices = build_strategy_choices(evidence)
    assert all("demo" not in choice["required_source_ids"] for options in choices.values() for choice in options)
    assert all("письменная обратная связь" not in choice["text"]
               and "прозрачность условий получения изделия" not in choice["text"]
               for options in choices.values() for choice in options)


@pytest.mark.parametrize("text", [
    "The course is accredited.",
    "The course is accredited 🎓.",
    "Гипотеза: курс аккредитован и включает индивидуальную поддержку 👩🏽‍🎨.",
    "Предлагаемый акцент ценности для проверки — аккредитация cafe\u0301.",
])
def test_unicode_and_unlisted_features_do_not_bypass_dynamic_scope(text):
    evidence = verification_inputs(invocation("course"))
    decision, _ = run_review([output(text, tuple(evidence))], evidence)
    assert decision["status"] == "rejected"


@pytest.mark.parametrize("case", CASES)
def test_all_outputs_pass_canonical_semantics_and_review_with_scoped_choices(case):
    req = invocation(case)
    evidence = verification_inputs(req)

    def select(payload, data):
        catalog = data["positioning_support_selection_catalog"]["evidence"]
        aliases = {identity: key for key, identity in catalog.items()}
        product_key = next(key for key, source in data["positioning_product_sources"].items()
                           if source["category"] == "product_truth")
        truth_id = data["positioning_product_sources"][product_key]["evidence_id"]
        for name, row in payload["outputs"].items():
            if name in {"offer", "RTB"}:
                row["text"] = sourced(product_key)
                required = {truth_id}
            else:
                options = data["positioning_strategy_choices"][name]
                choice = max(options, key=lambda item: len(item["required_source_ids"]))
                row["text"] = qualitative(choice["text"])
                required = {*choice["required_source_ids"], truth_id}
            for alias, identity in catalog.items():
                row["evidence_support"][alias] = identity in required
            if "primary_support_key" in row:
                row["primary_support_key"] = aliases[truth_id]

    model = SelectionModel(select)
    result = asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True,
                                             provider_schema_projection=True).execute(req))
    rows = list(result.payload["outputs"])
    assert len(rows) == 16
    assert len(model.calls) == 1
    assert next(row["text"] for row in rows if row["output_name"] == "offer") == CASES[case][1]
    assert next(row["text"] for row in rows if row["output_name"] == "RTB") == CASES[case][1]
    decision, _ = run_review(rows, evidence)
    assert decision["status"] == "verified", decision
    assert decision["findings"] == []


@pytest.mark.parametrize("case", CASES)
def test_closed_strategy_generation_renders_exact_authorized_proposals_and_binds_sources(case):
    req = invocation(case)
    evidence = verification_inputs(req)
    model = SelectionModel()
    result = asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True,
        strategy_selection=True, provider_schema_projection=True).execute(req))
    rows = list(result.payload["outputs"])
    assert len(rows) == 16
    choices = build_strategy_choices(evidence)
    for row in rows:
        if row["output_name"] in {"offer", "RTB"}:
            assert row["text"] == CASES[case][1]
        else:
            choice = next(choice for choice in choices[row["output_name"]] if choice["text"] == row["text"])
            assert set(choice["required_source_ids"]) <= set(row["evidence_ids"])
    decision, _ = run_review(rows, evidence)
    assert decision["status"] == "verified", decision


@pytest.mark.parametrize("selection", [
    {"mode": "QUALITATIVE", "value": "The course is accredited."},
    {"mode": "STRATEGY", "value": "strategy_unknown"},
    {"mode": "SOURCE", "value": "The course is accredited."},
])
def test_closed_strategy_selection_rejects_prose_and_unbound_keys(selection):
    from app.module_execution.executors.common import ExecutorOutputError, OutputFailureStage

    def tamper(payload, data):
        payload["outputs"]["category"]["text"] = selection

    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(PositioningExecutor(model_call=SelectionModel(tamper), support_selection_wire=True,
            strategy_selection=True).execute(invocation("course")))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


def test_closed_strategy_key_cannot_be_reused_for_another_output():
    from app.module_execution.executors.common import ExecutorOutputError, OutputFailureStage

    def tamper(payload, data):
        payload["outputs"]["category"]["text"] = {
            "mode": "STRATEGY", "value": next(iter(data["positioning_strategy_selection"]["differentiation"]))}

    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(PositioningExecutor(model_call=SelectionModel(tamper), support_selection_wire=True,
            strategy_selection=True).execute(invocation("course")))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


def test_closed_strategy_generation_cannot_promote_a_proposal_to_factual_inference():
    from app.module_execution.executors.common import ExecutorOutputError, OutputFailureStage

    def tamper(payload, data):
        payload["outputs"]["demand_context"]["kind"] = "INFERENCE"

    with pytest.raises(ExecutorOutputError) as caught:
        asyncio.run(PositioningExecutor(model_call=SelectionModel(tamper), support_selection_wire=True,
            strategy_selection=True).execute(invocation("course")))
    assert caught.value.stage is OutputFailureStage.SCHEMA_INVALID


@pytest.mark.parametrize("name", ["differentiation", "points_of_difference", "USP_directions"])
def test_closed_strategy_wire_preserves_canonical_hypothesis_only_outputs(name):
    from jsonschema import Draft202012Validator

    def inspect_schema(payload, data):
        candidate = model.calls[-1]["response_schema"]
        payload["outputs"][name]["kind"] = "RECOMMENDATION"
        assert not Draft202012Validator(candidate).is_valid(payload)
        payload["outputs"][name]["kind"] = "HYPOTHESIS"

    model = SelectionModel(inspect_schema)
    result = asyncio.run(PositioningExecutor(model_call=model, support_selection_wire=True,
        strategy_selection=True).execute(invocation("course")))
    assert next(row for row in result.payload["outputs"] if row["output_name"] == name)["kind"] == "HYPOTHESIS"


@pytest.mark.parametrize("durable", [False, True])
def test_production_composition_selects_closed_strategy_wire_only_for_durable_rollout(monkeypatch, durable):
    from app.config import settings
    from app.orchestration_runtime.composition import build_production_graph_runtime
    from tests.test_production_graph_worker import queue

    monkeypatch.setattr(settings, "POSITIONING_DURABLE_VERIFICATION_ENABLED", durable)
    monkeypatch.setattr(settings, "POSITIONING_SUPPORT_SELECTION_WIRE_ENABLED", True)
    monkeypatch.setattr(settings, "RESPONSES_WORKFLOW_GOVERNANCE_ENABLED", True)
    runtime = build_production_graph_runtime(queue=queue())
    executor = runtime.executors.resolve("positioning.v1")
    assert executor._strategy_selection is durable
