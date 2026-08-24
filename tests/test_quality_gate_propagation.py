import pytest
from app.marketing_orchestrator.quality_gates import *
from app.marketing_orchestrator.quality_gates.propagation import merge_records_by_id,confidence_within_parent_ceiling,compare_observed_at
from tests.quality_gate_helpers import UTC

def test_identity_union_is_stable_idempotent_and_rejects_unequal_collision():
    a=AssumptionRecord("asm_a","one",Materiality.MATERIAL);b=AssumptionRecord("asm_b","two",Materiality.NON_MATERIAL)
    assert merge_records_by_id(((b,a),(a,)),"assumption_id")== (a,b)
    with pytest.raises(QualityGateContractError):merge_records_by_id(((a,),(AssumptionRecord("asm_a","changed",Materiality.MATERIAL),)),"assumption_id")
def test_confidence_ceiling_and_freshness_are_closed():
    assert confidence_within_parent_ceiling(Confidence.LOW,[Confidence.MEDIUM])
    assert not confidence_within_parent_ceiling(Confidence.HIGH,[Confidence.MEDIUM,Confidence.LOW])
    assert not confidence_within_parent_ceiling(Confidence.LOW,[Confidence.UNKNOWN])
    assert compare_observed_at(UTC,UTC) is FreshnessComparison.SAME
    assert compare_observed_at(None,UTC) is FreshnessComparison.UNKNOWN
