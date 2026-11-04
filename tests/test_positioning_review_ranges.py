"""Production auditor contract over immutable server tokens and scoped sources."""
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from app.module_registry import ModuleId
from app.module_execution import UpstreamExecutionResult
from app.orchestration_runtime.claim_verification import (
    draft_tokens, review_contract, review_positioning, verification_inputs,
)
from tests.test_module_executors import FakeModel, dispatch, fact, request


def statement(text, *, name="offer", ids=("evd_product",)):
    return {"output_name": name, "text": text, "evidence_ids": list(ids), "parent_claim_ids": []}


def atom(start, end, *, category="strategy", kind="hypothesis", status="HYPOTHESIS", ids=()):
    return {"start_token": start, "end_token": end, "category": category,
            "kind": kind, "status": status, "support_ids": list(ids)}


def audit(rows, evidence, mutate=None):
    captured = {}

    async def model(**kwargs):
        data = json.loads(kwargs["text"])
        report = {"draft_fingerprint": data["draft_fingerprint"], "assessment": "APPROVE", "reviews": {
            name: {"atoms_complete": True, "output_fulfilled": True, "claims": [atom(0, len(output["tokens"]))]}
            for name, output in data["outputs"].items()
        }}
        if mutate:
            mutate(report, data)
        captured.update(data=data, schema=kwargs["response_schema"], report=report)
        return json.dumps(report, ensure_ascii=False)

    result = SimpleNamespace(payload={"outputs": rows})
    return asyncio.run(review_positioning(model, result, evidence)), captured


def source(text, *, role="product_truth"):
    return {"text": text, "role": role}


def supported(report, data):
    for name, output in data["outputs"].items():
        report["reviews"][name]["claims"] = [atom(
            0, len(output["tokens"]), category="product", kind="fact", status="SUPPORTED",
            ids=output["evidence"],
        )]


def test_schema_and_server_reject_another_outputs_source():
    rows = [statement("Explore a useful angle.", ids=("evd_product",)),
            statement("Explore another angle.", name="target", ids=("evd_other",))]
    evidence = {"evd_product": source("Materials included."), "evd_other": source("Beginners.", role="audience")}

    def foreign(report, data):
        report["reviews"]["offer"]["claims"][0]["support_ids"] = ["evd_other"]

    decision, seen = audit(rows, evidence, foreign)
    assert set(seen["data"]["outputs"]["offer"]["evidence"]) == {"evd_product"}
    assert not Draft202012Validator(seen["schema"]).is_valid(seen["report"])
    assert decision == {"status": "blocked", "reason": "invalid_claim_review"}


@pytest.mark.parametrize("change", ["omitted_token", "wrong_hash", "reversed", "empty", "outside", "missing_output"])
def test_invalid_ranges_or_draft_identity_block_approval(change):
    rows = [statement("Explore a useful angle.")]

    def mutate(report, data):
        claim = report["reviews"]["offer"]["claims"][0]
        if change == "omitted_token":
            claim["end_token"] -= 1
        elif change == "wrong_hash":
            report["draft_fingerprint"] = "0" * 64
        elif change == "reversed":
            claim.update(start_token=2, end_token=1)
        elif change == "empty":
            claim.update(start_token=1, end_token=1)
        elif change == "outside":
            claim["end_token"] += 1
        else:
            report["reviews"] = {}

    decision, _ = audit(rows, {"evd_product": source("Materials included.")}, mutate)
    assert decision == {"status": "blocked", "reason": "invalid_claim_review"}


@pytest.mark.parametrize("text", [
    "  Test 🎨 whether learners value cafe\u0301 imagery.\n",
    "Проверить интерес 👩🏽‍🎨 к съёмке е\u0308лки.\t",
    "🔬\u200d🎨  Test\u00a0a new angle.\r\n",
])
def test_unicode_tokens_roundtrip_without_normalization(text):
    decision, captured = audit([statement(text)], {"evd_product": source(text)}, supported)
    tokens = captured["data"]["outputs"]["offer"]["tokens"]
    assert "".join(token["text"] for token in tokens) == text
    assert draft_tokens(text) == [token["text"] for token in tokens]
    assert [token["id"] for token in tokens] == list(range(len(tokens)))
    assert decision["status"] == "verified"
    assert decision["reviews"][0]["claims"][0]["span"] == text


def test_overlapping_atoms_can_assess_two_facts_within_a_sentence():
    text = "Materials are included and collection happens later."

    def multiple(report, data):
        count = len(data["outputs"]["offer"]["tokens"])
        report["reviews"]["offer"]["claims"] = [
            atom(0, count, category="product", kind="fact", status="SUPPORTED", ids=("evd_product",)),
            atom(4, count, category="fulfillment", kind="fact", status="UNSUPPORTED"),
        ]

    decision, _ = audit([statement(text)], {"evd_product": source(text)}, multiple)
    assert decision["coverage"] == "complete"
    assert decision["status"] == "rejected"
    assert len(decision["reviews"][0]["claims"]) == 2
    assert decision["findings"] == [{"output_name": "offer", "claim_index": 1,
                                     "status": "UNSUPPORTED", "reason": "review_rejected"}]


def test_separate_atomic_ranges_of_a_complete_source_sentence_are_supported():
    text = "Participants complete practical exercises and receive written feedback."

    def separate(report, data):
        count = len(data["outputs"]["offer"]["tokens"])
        report["reviews"]["offer"]["claims"] = [
            atom(0, 5, category="product", kind="fact", status="SUPPORTED", ids=("evd_product",)),
            atom(5, count, category="product", kind="fact", status="SUPPORTED", ids=("evd_product",)),
        ]

    decision, _ = audit([statement(text)], {"evd_product": source(text)}, separate)
    assert decision["status"] == "verified"
    assert len(decision["reviews"][0]["claims"]) == 2


def test_complete_character_coverage_does_not_imply_atomic_completeness():
    def incomplete(report, data):
        report["reviews"]["offer"]["atoms_complete"] = False

    decision, _ = audit([statement("Test whether beginners value knowing what to practice next.")], {}, incomplete)
    assert decision["coverage"] == "complete"
    assert not decision["findings"]
    assert decision["status"] == "blocked"


def test_hypothesis_cannot_authorize_an_unsupported_product_property():
    def product(report, data):
        report["reviews"]["offer"]["claims"][0]["category"] = "product"

    decision, _ = audit([statement("Learners receive personal feedback.")],
                        {"evd_product": source("Learners receive written feedback.")}, product)
    assert decision["status"] == "rejected"
    assert decision["findings"][0]["reason"] == "unverified_factual_premise"


@pytest.mark.parametrize("text", [
    "Hypothesis: learners receive personal feedback.",
    "Test whether the online course attracts beginners.",
    "Предлагаем акцент на том, что курс включает домашние задания.",
])
def test_strategy_label_cannot_hide_a_known_factual_premise(text):
    decision, _ = audit([statement(text)], {"evd_product": source("Learners practice photography.")})
    assert decision["status"] == "rejected"
    assert decision["findings"][0]["reason"] == "unverified_factual_premise"


@pytest.mark.parametrize("split", [False, True])
def test_unknown_predicate_cannot_be_approved_as_strategy(split):
    def mutate(report, data):
        if split:
            count = len(data["outputs"]["offer"]["tokens"])
            report["reviews"]["offer"]["claims"] = [atom(index, index + 1) for index in range(count)]

    decision, _ = audit([statement("The course is accredited.")], {}, mutate)
    assert decision["status"] == "rejected"
    assert any(finding["reason"] == "unverified_factual_premise" for finding in decision["findings"])


def test_dividing_a_factual_premise_between_strategy_ranges_cannot_hide_it():
    text = "Learners receive personal feedback."

    def split(report, data):
        count = len(data["outputs"]["offer"]["tokens"])
        report["reviews"]["offer"]["claims"] = [atom(index, index + 1) for index in range(count)]

    decision, _ = audit([statement(text)], {"evd_product": source("Learners receive written feedback.")}, split)
    assert decision["status"] == "rejected"
    assert any(finding["reason"] == "unverified_factual_premise" for finding in decision["findings"])


@pytest.mark.parametrize("text,kind,status", [
    ("Test whether beginners value knowing what to practice next.", "hypothesis", "HYPOTHESIS"),
    ("Ask participants whether the timing meets their needs.", "recommendation", "RECOMMENDATION"),
])
def test_prospective_research_questions_and_recommendations_remain_useful(text, kind, status):
    def research(report, data):
        report["reviews"]["offer"]["claims"][0].update(kind=kind, status=status)

    decision, _ = audit([statement(text)], {}, research)
    assert decision["status"] == "verified"
    assert decision["findings"] == []


def test_server_resolves_the_entire_eligible_source_without_auditor_quotations():
    text = "Participants complete practical exercises and receive written feedback."
    decision, captured = audit([statement(text)], {"evd_product": source(text)}, supported)
    assert decision["status"] == "verified"
    assert decision["reviews"][0]["claims"][0]["support"] == [{"evidence_id": "evd_product", "quote": text}]
    sent_atom = captured["report"]["reviews"]["offer"]["claims"][0]
    assert "span" not in sent_atom and "quote" not in sent_atom


def test_source_partial_removal_cannot_discard_fulfillment_conditions():
    full = "Materials are included. Participants collect the piece another day after firing."
    decision, _ = audit([statement("Materials are included.")], {"evd_product": source(full)}, supported)
    assert decision["status"] == "rejected"
    assert decision["findings"][0]["reason"] == "no_exact_eligible_assertion"


def test_real_verification_inputs_block_auditor_approval_of_no_further_actions():
    truth = "Материалы и обжиг включены. Участники забирают изделия после обжига в другой день."
    invocation = request(ModuleId.POSITIONING, facts=(
        fact("product", "Мастер-класс керамики"), fact("target_or_target_hypothesis", "Взрослые"),
        fact("product_truth", truth),
    ))
    evidence = verification_inputs(invocation)
    identity = next(key for key, value in evidence.items() if value["role"] == "product_truth")
    assert evidence[identity]["requires_follow_up"] is True
    decision, _ = audit([statement("Никаких дальнейших действий не потребуется.", ids=(identity,))], evidence)
    assert decision["assessment"] == "APPROVE"
    assert decision["status"] == "rejected"
    assert decision["fulfillment_guarantee"] == "available"
    assert any(finding["status"] == "CONTRADICTED" and finding["reason"] == "required_follow_up"
               for finding in decision["findings"])


def test_ambiguous_fulfillment_source_explicitly_has_no_structured_guarantee():
    invocation = request(ModuleId.POSITIONING, facts=(
        fact("product_truth", "Возможность выдачи изделия и сроки нужно уточнить у мастера."),
    ))
    evidence = verification_inputs(invocation)
    identity, = evidence
    assert evidence[identity]["requires_follow_up"] is None
    decision, _ = audit([statement("Ask participants whether the timing meets their needs.", ids=(identity,))], evidence)
    assert decision["fulfillment_guarantee"] == "unavailable"


def test_fingerprint_binds_the_evidence_and_unchanged_unicode_draft():
    rows = [statement("Explore cafe\u0301 imagery 🎨.")]
    original, _ = review_contract(rows, {"evd_product": source("Owner fact.")})
    changed_text, _ = review_contract([statement("Explore café imagery 🎨.")], {"evd_product": source("Owner fact.")})
    changed_source, _ = review_contract(rows, {"evd_product": source("Other fact.")})
    assert len({original["draft_fingerprint"], changed_text["draft_fingerprint"], changed_source["draft_fingerprint"]}) == 3


def competitor_parent():
    from tests.test_module_executors import analyzer

    site = analyzer()
    site.analyze.return_value.url_summaries[0]["main_text_excerpt"] = (
        "The competitor site states: A public page advertises scheduling for local businesses."
    )
    def observed(payload, data):
        external = next(item for item in data["local_evidence"] if item["source_class"] == "EXTERNAL_PRIMARY")
        payload["outputs"][0].update(kind="OBSERVATION", text=external["value"],
                                       evidence_ids=[external["evidence_id"]])

    return dispatch(request(ModuleId.COMPETITOR_ANALYSIS, outputs=("observable_positioning",)), FakeModel(observed), site)


def parent_request(parent):
    return request(ModuleId.POSITIONING, upstream=(UpstreamExecutionResult(producer_node_id="competitor", result=parent),))


def test_exact_factual_competitor_parent_is_available_only_when_cited():
    parent = competitor_parent()
    claim, = parent.normalized_result.claims
    evidence = verification_inputs(parent_request(parent))
    assert evidence[claim.claim_id] == {"role": "competitor", "text": claim.value}
    row = statement(claim.value, name="points_of_parity", ids=())
    row["parent_claim_ids"] = [claim.claim_id]

    def parent_support(report, data):
        report["reviews"]["points_of_parity"]["claims"] = [atom(
            0, len(data["outputs"]["points_of_parity"]["tokens"]), category="competitor", kind="fact",
            status="SUPPORTED", ids=(claim.claim_id,),
        )]

    decision, _ = audit([row], evidence, parent_support)
    assert decision["status"] == "verified"
    row["parent_claim_ids"] = []
    decision, _ = audit([row], evidence, parent_support)
    assert decision == {"status": "blocked", "reason": "invalid_claim_review"}


@pytest.mark.parametrize("mode", ["hypothesis", "empty_evidence", "missing_evidence"])
def test_unconfirmed_or_unresolved_parent_cannot_become_verifier_evidence(mode):
    from app.marketing_orchestrator.quality_gates.contracts import ClaimType

    parent = competitor_parent()
    claim, = parent.normalized_result.claims
    if mode == "hypothesis":
        claim = replace(claim, claim_type=ClaimType.HYPOTHESIS)
    else:
        claim = replace(claim, evidence_ids=() if mode == "empty_evidence" else ("evd_missing_parent_source",))
    parent = replace(parent, payload={}, normalized_result=replace(parent.normalized_result, claims=(claim,)))
    evidence = verification_inputs(parent_request(parent))
    assert claim.claim_id not in evidence
