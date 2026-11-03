import pytest

from app.module_execution.errors import ModuleExecutionContractError
from app.orchestration_runtime.claim_verification import (
    ClaimReview,
    ClaimStatus,
    DraftStatement,
    OutputReview,
    ReviewEvidence,
    SupportFragment,
    verify_claim_review,
)


def review(span, *, category="product", kind="fact", status="SUPPORTED",
           quote=None, evidence_id="evd_product", no_follow_up=False):
    return ClaimReview(span=span, category=category, kind=kind, status=status,
                       support=[] if quote is None else [SupportFragment(evidence_id=evidence_id, quote=quote)],
                       asserts_no_follow_up=no_follow_up)


def verify(text, source, *claims, cited=("evd_product",)):
    return verify_claim_review(
        {"offer": DraftStatement(text, frozenset(cited))},
        {"evd_product": source},
        (OutputReview(output_name="offer", claims=list(claims)),),
    )


@pytest.mark.parametrize(("draft", "source", "role"), [
    ("A demo exercise is used every week.", "One demo exercise compares two photographs.", "demonstration"),
    ("Learners receive personal feedback.", "Learners receive written feedback.", "product_truth"),
    ("Learners do homework.", "Learners complete practical exercises.", "product_truth"),
    ("The lessons are online.", "Learners complete practical exercises.", "product_truth"),
    ("Participants are guaranteed results.", "Participants practice the technique.", "product_truth"),
    ("The course outperforms competitors.", "Learners receive written feedback.", "product_truth"),
])
def test_positive_review_cannot_authorize_stronger_or_unrelated_assertion(draft, source, role):
    findings = verify(draft, ReviewEvidence(source, role), review(draft, quote=source))
    assert [(f.status, f.reason) for f in findings] == [
        (ClaimStatus.UNVERIFIABLE, "no_exact_eligible_assertion"),
    ]


def test_fulfillment_constraint_overrides_positive_recommendation_verdict():
    draft = "No action is needed after the workshop."
    source = ReviewEvidence("Collect the piece another day after firing.", "product_truth", requires_follow_up=True)
    findings = verify(draft, source, review(
        draft, category="fulfillment", kind="recommendation", status="RECOMMENDATION", no_follow_up=True,
    ))
    assert [(f.status, f.reason) for f in findings] == [(ClaimStatus.CONTRADICTED, "required_follow_up")]


def test_partial_quote_cannot_drop_the_fulfillment_condition():
    full = "Collect the piece after firing, on a later day."
    fragment = "Collect the piece after firing"
    findings = verify(fragment, ReviewEvidence(full, "product_truth"),
                      review(fragment, category="fulfillment", quote=fragment))
    assert findings[0].status == ClaimStatus.UNVERIFIABLE


def test_review_cannot_add_a_citation_or_invent_a_source_quote():
    text = "Written feedback is included."
    source = ReviewEvidence(text, "product_truth")
    with pytest.raises(ModuleExecutionContractError, match="support identity"):
        verify(text, source, review(text, quote=text), cited=())
    with pytest.raises(ModuleExecutionContractError, match="support identity"):
        verify(text, source, review(text, quote="Personal feedback"))


def test_review_requires_exact_coverage_even_when_the_omitted_text_is_last():
    text = "Written feedback is included. Guaranteed progress."
    source = ReviewEvidence("Written feedback is included.", "product_truth")
    with pytest.raises(ModuleExecutionContractError, match="text coverage"):
        verify(text, source, review(source.text, quote=source.text))


def test_complete_fact_and_distinct_strategic_hypothesis_are_permitted():
    source = ReviewEvidence("Written feedback is included.", "product_truth")
    strategy = " Test whether beginners value knowing what to practice next."
    assert not verify(source.text + strategy, source, review(source.text, quote=source.text),
                      review(strategy, category="strategy", kind="hypothesis", status="HYPOTHESIS"))


def test_unknown_product_conditions_can_be_an_explicit_validation_recommendation():
    text = "Ask participants whether the timing meets their needs."
    assert not verify(text, ReviewEvidence("", "product_truth"),
                      review(text, category="strategy", kind="recommendation", status="RECOMMENDATION"))


def test_even_exact_demonstration_cannot_be_approved_as_product_property():
    text = "The sample uses a pottery wheel."
    findings = verify(text, ReviewEvidence(text, "demonstration"), review(text, quote=text))
    assert findings[0].reason == "no_exact_eligible_assertion"


def test_review_must_cover_every_output_once():
    draft = {"offer": DraftStatement("A.", frozenset()), "target": DraftStatement("B.", frozenset())}
    item = OutputReview(output_name="offer", claims=[review("A.", status="UNSUPPORTED")])
    for incomplete in ((item,), (item, item)):
        with pytest.raises(ModuleExecutionContractError, match="output coverage"):
            verify_claim_review(draft, {}, incomplete)


def test_cli_reports_only_bounded_findings(tmp_path, monkeypatch, capsys):
    import json
    import sys

    from tools.positioning_claim_verification import main

    draft = "No action is needed after the workshop."
    path = tmp_path / "review.json"
    path.write_text(json.dumps({
        "draft": {"offer": {"text": draft, "evidence_ids": ["evd_product"]}},
        "evidence": {"evd_product": {
            "text": "Collect the piece another day.", "role": "product_truth", "requires_follow_up": True,
        }},
        "reviews": [OutputReview(output_name="offer", claims=[review(
            draft, category="fulfillment", kind="hypothesis", status="HYPOTHESIS", no_follow_up=True,
        )]).model_dump()],
    }), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["positioning_claim_verification", str(path)])
    assert main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result == {"status": "rejected", "findings": [{
        "output_name": "offer", "claim_index": 0, "status": "CONTRADICTED", "reason": "required_follow_up",
    }]}


def test_workflow_budget_separates_operations_without_allowing_repeat():
    from app.orchestration_runtime.retry_policy import RetryGovernanceError, complete, new_policy, reserve

    first = {"provider_call_id": "generation", "node_id": "positioning", "max_output_tokens": 4000}
    verification = {**first, "provider_call_id": "audit", "operation": "positioning_verification.v1"}
    policy = reserve(new_policy(1, 8000), first)
    policy = complete(policy, {**first, "outcome": "success", "outcome_unknown": False})
    policy = reserve(policy, verification)
    with pytest.raises(RetryGovernanceError, match="invalid_provider_receipt"):
        complete(policy, {**first, "provider_call_id": "audit", "outcome": "success", "outcome_unknown": False})
    with pytest.raises(RetryGovernanceError, match="previous_outcome"):
        reserve(policy, {**verification, "provider_call_id": "duplicate"})
    policy = complete(policy, {**verification, "outcome": "success", "outcome_unknown": False})
    with pytest.raises(RetryGovernanceError, match="previous_outcome"):
        reserve(policy, {**verification, "provider_call_id": "after_success"})
