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
            factual = name in {"offer", "RTB"} and bool(exact_ids)
            reviews[name] = {"atoms_complete": True, "output_fulfilled": True, "claims": [{
                "span_id": "whole",
                "category": "product" if factual else "strategy",
                "kind": "fact" if factual else "hypothesis",
                "status": "SUPPORTED" if factual else "HYPOTHESIS",
                "support_ids": exact_ids if factual else [],
            }]}
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


def test_several_recommendations_inside_a_complete_bound_message_plan_are_reviewable():
    evidence = verification_inputs(invocation("course"))
    choice = dynamic_choice(evidence, "message_hierarchy")

    def separate(report, data):
        report["reviews"]["message_hierarchy"]["claims"] = [
            {"span_id": identity, "category": "strategy", "kind": "recommendation",
             "status": "RECOMMENDATION", "support_ids": []}
            for identity in data["outputs"]["message_hierarchy"]["spans"] if identity.startswith("sentence_")
        ]

    decision, _ = run_review([output(choice["text"], choice["required_source_ids"], name="message_hierarchy")], evidence, separate)
    assert decision["status"] == "verified"
    assert len(decision["reviews"][0]["claims"]) > 1


@pytest.mark.parametrize("category", ["product", "audience", "competitor", "fulfillment"])
def test_exact_dynamic_proposal_does_not_depend_on_auditor_category_label(category):
    evidence = verification_inputs(invocation("course"))
    choice = dynamic_choice(evidence)

    def relabel(report, data):
        report["reviews"]["value_proposition"]["claims"][0]["category"] = category

    decision, _ = run_review([output(choice["text"], choice["required_source_ids"])], evidence, relabel)
    assert decision["status"] == "verified", decision
    assert decision["findings"] == []


@pytest.mark.parametrize("case", CASES)
def test_missing_dynamic_dependency_cannot_be_approved(case):
    evidence = verification_inputs(invocation(case))
    choice = dynamic_choice(evidence)
    for omitted in choice["required_source_ids"]:
        ids = set(choice["required_source_ids"]) - {omitted}
        decision, captured = run_review([output(choice["text"], ids)], evidence)
        assert decision["status"] == "rejected"
        assert choice not in captured["data"]["outputs"]["value_proposition"]["strategy_choices"]
        assert decision["findings"][0]["reason"] == "unverified_factual_premise"


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
    assert decision["findings"][0]["reason"] == "unverified_factual_premise"


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
