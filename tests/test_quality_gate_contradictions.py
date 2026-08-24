from datetime import timedelta
import pytest
from app.marketing_orchestrator.quality_gates import *
from tests.quality_gate_helpers import *

def _case(left_source,right_source,left_at=UTC,right_at=UTC,left_id="evd_left",right_id="evd_right"):
    ev=(EvidenceRecord("evd_left",left_source,"left",left_at),EvidenceRecord("evd_right",right_source,"right",right_at))
    cs=(claim("clm_left",evidence_ids=("evd_left",)),claim("clm_right",evidence_ids=("evd_right",)))
    r=result(claims=cs,evidence=ev)
    c=ContradictionInput("ctr_one",ContradictionSide(claim_id="clm_left",object_key="object",segment_key="segment",period_key="period",metric_definition_key="metric",evidence_id=left_id),ContradictionSide(claim_id="clm_right",object_key="object",segment_key="segment",period_key="period",metric_definition_key="metric",evidence_id=right_id))
    return batch(results=(r,),contradictions=(c,))
def test_first_party_equal_or_newer_is_only_precedence():
    for at in (UTC,UTC+timedelta(days=1)):
        out=QualityGateEvaluator().evaluate(_case(EvidenceSourceClass.FIRST_PARTY,EvidenceSourceClass.GENERIC_BENCHMARK,at,UTC))
        rec=out.contradiction_records[0];assert rec.state is ContradictionState.PRIORITIZED;assert rec.preferred_claim_id=="clm_left";assert not out.derived_limitations
def test_older_and_unselected_are_unresolved_with_material_limit():
    for b in (_case(EvidenceSourceClass.FIRST_PARTY,EvidenceSourceClass.GENERIC_BENCHMARK,UTC-timedelta(days=1),UTC),batch(results=(result(claims=(claim("clm_left"),claim("clm_right"))),),contradictions=(ContradictionInput("ctr_one",ContradictionSide(claim_id="clm_left",object_key="o",segment_key="s",period_key="p",metric_definition_key="m"),ContradictionSide(claim_id="clm_right",object_key="o",segment_key="s",period_key="p",metric_definition_key="m")),))):
        out=QualityGateEvaluator().evaluate(b);assert out.contradiction_records[0].state is ContradictionState.UNRESOLVED;assert len(out.derived_limitations)==1;assert out.gate_decisions[0].gate_outcome is GateOutcome.FAIL
def test_one_selected_or_wrong_membership_rejected():
    with pytest.raises(QualityGateContractError):QualityGateEvaluator().evaluate(_case(EvidenceSourceClass.UNKNOWN,EvidenceSourceClass.UNKNOWN,right_id=None))
    with pytest.raises(QualityGateContractError):QualityGateEvaluator().evaluate(_case(EvidenceSourceClass.UNKNOWN,EvidenceSourceClass.UNKNOWN,left_id="evd_right"))

@pytest.mark.parametrize("field",["object_key","segment_key","period_key","metric_definition_key"])
def test_each_key_mismatch_is_incomparable(field):
    b=_case(EvidenceSourceClass.FIRST_PARTY,EvidenceSourceClass.GENERIC_BENCHMARK)
    left=b.contradictions[0].left; values={n:getattr(left,n) for n in ("object_key","segment_key","period_key","metric_definition_key")}; values[field]+="_other"
    side=ContradictionSide(claim_id="clm_right",evidence_id="evd_right",**values)
    c=ContradictionInput("ctr_one",left,side)
    out=QualityGateEvaluator().evaluate(EvaluationBatch("bat_one",b.results,(c,)))
    assert out.contradiction_records[0].state is ContradictionState.INCOMPARABLE
    assert out.contradiction_records[0].preferred_claim_id is None

def test_side_reversal_changes_fingerprint_but_not_preferred_claim():
    b=_case(EvidenceSourceClass.FIRST_PARTY,EvidenceSourceClass.GENERIC_BENCHMARK)
    c=b.contradictions[0]; reverse=EvaluationBatch("bat_one",b.results,(ContradictionInput("ctr_one",c.right,c.left),))
    assert b.batch_fingerprint!=reverse.batch_fingerprint
    a=QualityGateEvaluator().evaluate(b).contradiction_records[0]; z=QualityGateEvaluator().evaluate(reverse).contradiction_records[0]
    assert (a.state,a.preferred_claim_id)==(z.state,z.preferred_claim_id)

def test_incomparable_still_validates_selected_reference_and_membership_first():
    b=_case(EvidenceSourceClass.FIRST_PARTY,EvidenceSourceClass.GENERIC_BENCHMARK)
    left=b.contradictions[0].left
    wrong=ContradictionSide(claim_id="clm_right",object_key="different",segment_key="segment",period_key="period",metric_definition_key="metric",evidence_id="evd_missing")
    with pytest.raises(QualityGateContractError):QualityGateEvaluator().evaluate(EvaluationBatch("bat_one",b.results,(ContradictionInput("ctr_one",left,wrong),)))
    unattached=ContradictionSide(claim_id="clm_right",object_key="different",segment_key="segment",period_key="period",metric_definition_key="metric",evidence_id="evd_left")
    with pytest.raises(QualityGateContractError):QualityGateEvaluator().evaluate(EvaluationBatch("bat_one",b.results,(ContradictionInput("ctr_one",left,unattached),)))

def test_incomparable_skips_freshness_precedence(monkeypatch):
    b=_case(EvidenceSourceClass.FIRST_PARTY,EvidenceSourceClass.GENERIC_BENCHMARK)
    left=b.contradictions[0].left;right=ContradictionSide(claim_id="clm_right",object_key="different",segment_key="segment",period_key="period",metric_definition_key="metric",evidence_id="evd_right")
    monkeypatch.setattr("app.marketing_orchestrator.quality_gates.evaluator.compare_observed_at",lambda *_:(_ for _ in ()).throw(AssertionError("precedence inspected")))
    assert QualityGateEvaluator().evaluate(EvaluationBatch("bat_one",b.results,(ContradictionInput("ctr_one",left,right),))).contradiction_records[0].state is ContradictionState.INCOMPARABLE
