"""Source identity cannot launder another entity's facts into product outputs."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.module_execution import UpstreamExecutionResult
from app.module_execution.executors.positioning import PositioningExecutor
from app.module_execution.executors.positioning_strategy import STRATEGY_OPTIONS
from app.module_registry import ModuleId
from app.orchestration_runtime.claim_verification import review_positioning, verification_inputs
from tests.test_module_executors import FakeModel, dispatch, request
from tests.test_positioning_review_ranges import atom, audit, source, statement


COMPETITIVE_OUTPUTS = (
    "category", "frame_of_reference", "differentiation", "points_of_parity", "points_of_difference",
)
PRODUCT_OUTPUTS = (
    "value_proposition", "positioning_statement", "offer", "message_hierarchy", "RTB", "USP_directions",
)


def factual_auditor(category, identity="evd_source"):
    def mutate(report, data):
        for name, row in data["outputs"].items():
            report["reviews"][name]["claims"] = [atom(
                0, len(row["tokens"]), category=category, kind="fact", status="SUPPORTED", ids=(identity,),
            )]
    return mutate


@pytest.mark.parametrize("name", PRODUCT_OUTPUTS)
@pytest.mark.parametrize("text", [
    "A certificate is included.",
    "The competitor site states: A certificate is included.",
    "На сайте конкурента указано: участники получают сертификат.",
])
def test_competitor_source_cannot_support_own_product_output_even_when_auditor_calls_it_competitor(name, text):
    row = statement(text, name=name, ids=())
    row["parent_claim_ids"] = ["clm_competitor"]
    decision, _ = audit([row], {"clm_competitor": source(text, role="competitor")},
                        factual_auditor("competitor", "clm_competitor"))
    assert decision["status"] in {"rejected", "blocked"}


@pytest.mark.parametrize("name", COMPETITIVE_OUTPUTS)
def test_competitor_property_requires_explicit_attribution_even_in_a_comparison_output(name):
    text = "A certificate is included."
    row = statement(text, name=name, ids=())
    row["parent_claim_ids"] = ["clm_competitor"]
    decision, _ = audit([row], {"clm_competitor": source(text, role="competitor")},
                        factual_auditor("competitor", "clm_competitor"))
    assert decision["status"] in {"rejected", "blocked"}


@pytest.mark.parametrize("name", COMPETITIVE_OUTPUTS)
@pytest.mark.parametrize("text", [
    "The competitor site states: A certificate is included.",
    "На сайте конкурента указано: участники получают сертификат.",
])
def test_attributed_competitor_fact_can_support_an_appropriate_comparison_output(name, text):
    row = statement(text, name=name, ids=())
    row["parent_claim_ids"] = ["clm_competitor"]
    decision, _ = audit([row], {"clm_competitor": source(text, role="competitor")},
                        factual_auditor("competitor", "clm_competitor"))
    assert decision["status"] == "verified"


@pytest.mark.parametrize("name", ("target", "JTBD_frame", "demand_context"))
def test_audience_source_is_eligible_for_audience_and_need_outputs(name):
    text = "Adults without previous experience."
    decision, _ = audit([statement(text, name=name, ids=("evd_source",))],
                        {"evd_source": source(text, role="audience")}, factual_auditor("audience"))
    assert decision["status"] == "verified"


@pytest.mark.parametrize("name", PRODUCT_OUTPUTS)
def test_audience_profile_cannot_authorize_a_product_feature(name):
    text = "Participants receive certificates."
    decision, _ = audit([statement(text, name=name, ids=("evd_source",))],
                        {"evd_source": source(text, role="audience")}, factual_auditor("audience"))
    assert decision["status"] in {"rejected", "blocked"}


def test_product_truth_is_not_an_audience_profile():
    text = "No professional equipment is required."
    decision, _ = audit([statement(text, name="target", ids=("evd_source",))],
                        {"evd_source": source(text)}, factual_auditor("product"))
    assert decision["status"] in {"rejected", "blocked"}


@pytest.mark.parametrize("name,expected", [("RTB", "verified"), ("offer", "rejected"), ("value_proposition", "rejected")])
def test_demonstration_is_limited_to_proof_output(name, expected):
    text = "A demonstration sample shows a glazed cup."
    decision, _ = audit([statement(text, name=name, ids=("evd_source",))],
                        {"evd_source": source(text, role="demonstration")}, factual_auditor("product"))
    if expected == "verified":
        assert decision["status"] == expected
    else:
        assert decision["status"] in {"rejected", "blocked"}


def test_production_executor_and_reviewer_cannot_launder_competitor_certificate_into_own_value_proposition():
    text = "A certificate is included."
    site = SimpleNamespace(analyze=AsyncMock(return_value=SimpleNamespace(url_summaries=[{
        "ok": True, "url": "https://competitor.example/page", "final_url": "https://competitor.example/page",
        "main_text_excerpt": text,
    }])))

    def observed(payload, data):
        external = next(row for row in data["local_evidence"] if row["source_class"] == "EXTERNAL_PRIMARY")
        payload["outputs"][0].update(kind="OBSERVATION", text=external["value"],
                                       evidence_ids=[external["evidence_id"]])

    parent = dispatch(request(ModuleId.COMPETITOR_ANALYSIS, outputs=("observable_positioning",)),
                      FakeModel(observed), site=site)
    parent_id = parent.normalized_result.claims[0].claim_id
    invocation = request(ModuleId.POSITIONING, upstream=(
        UpstreamExecutionResult(producer_node_id="competitor", result=parent),
    ))

    def mutate(payload, data):
        for row in payload["outputs"]:
            if row["output_name"] != "RTB":
                row["text"] = text if row["output_name"] == "value_proposition" else STRATEGY_OPTIONS[row["output_name"]][0]

    async def exercise():
        result = await PositioningExecutor(model_call=FakeModel(mutate=mutate, use_parents=True)).execute(invocation)
        evidence = verification_inputs(invocation)
        assert evidence[parent_id]["role"] == "competitor"

        async def auditor(**kwargs):
            data = json.loads(kwargs["text"])
            reviews = {}
            for name, row in data["outputs"].items():
                ids, category, kind, status = [], "strategy", "hypothesis", "HYPOTHESIS"
                if name == "RTB":
                    rendered = "".join(token["text"] for token in row["tokens"])
                    ids = [identity for identity, item in row["evidence"].items()
                           if item["text"] == rendered and item["role"] == "product_truth"]
                    category, kind, status = "product", "fact", "SUPPORTED"
                if name == "value_proposition":
                    ids, category, kind, status = [parent_id], "competitor", "fact", "SUPPORTED"
                reviews[name] = {"atoms_complete": True, "output_fulfilled": True, "claims": [atom(
                    0, len(row["tokens"]), category=category, kind=kind, status=status, ids=ids,
                )]}
            return json.dumps({"draft_fingerprint": data["draft_fingerprint"], "assessment": "APPROVE", "reviews": reviews})

        decision = await review_positioning(auditor, result, evidence)
        assert decision["status"] in {"rejected", "blocked"}
        if decision["status"] == "rejected":
            assert any(finding["output_name"] == "value_proposition" for finding in decision["findings"])

    asyncio.run(exercise())
