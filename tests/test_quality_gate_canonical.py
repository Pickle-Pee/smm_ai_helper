from datetime import datetime,timedelta,timezone
import pytest
from app.marketing_orchestrator.quality_gates.canonical import rfc8785_dumps,derive_id
from tests.quality_gate_helpers import *

def test_fixed_fingerprint_and_stability():
    a=batch(); b=batch(); assert a.batch_fingerprint==b.batch_fingerprint
    assert a.batch_fingerprint=="20c9fb5190f14cfdbf629821ed4a3a48a257a4960c6b9d3cb1ca8d42beb9a33b"
def test_tagged_values_distinguish_int_float_and_signed_zero():
    vals=[batch(results=(result(claims=(claim(value=x),)),)).batch_fingerprint for x in (1,1.0,0.0,-0.0)]
    assert len(set(vals))==4
def test_timestamp_offset_normalization_and_field_sensitivity():
    a=batch(evaluation_at=datetime(2025,1,1,tzinfo=timezone.utc))
    b=batch(evaluation_at=datetime(2025,1,1,3,tzinfo=timezone(timedelta(hours=3))))
    assert a.batch_fingerprint==b.batch_fingerprint
    assert a.batch_fingerprint!=batch().batch_fingerprint
def test_rfc_utf16_key_order_and_escaping():
    assert rfc8785_dumps({"\ue000":1,"😀":2})=='{"😀":2,"\ue000":1}'
    assert rfc8785_dumps({"x":"\b\n\"\\\u0001"})=='{"x":"\\b\\n\\\"\\\\\\u0001"}'
def test_fixed_derived_id_vector():
    got,_=derive_id("lim",("quality-gates-v1","limitation","0"*64,"res_one","ctr_one","UNRESOLVED_CONTRADICTION"))
    assert got=="lim_2b42fd3a91882bc24469ecfa3334aed0"
    exclusion,_=derive_id("exc",("quality-gates-v1","exclusion","0"*64,"CLAIM","","clm_one","UNRESOLVED_CONTRADICTION","ctr_one"))
    assert exclusion=="exc_a2e97bf393be35ca457a154117ceb728"

def test_every_contradiction_side_field_and_side_position_affect_fingerprint():
    from app.marketing_orchestrator.quality_gates import ContradictionSide,ContradictionInput,EvaluationBatch
    results=(result(claims=(claim("clm_left"),claim("clm_right"))),)
    left=ContradictionSide(claim_id="clm_left",object_key="o",segment_key="s",period_key="p",metric_definition_key="m");right=ContradictionSide(claim_id="clm_right",object_key="o",segment_key="s",period_key="p",metric_definition_key="m")
    def fp(l=left,r=right):return EvaluationBatch("bat_one",results,(ContradictionInput("ctr_one",l,r),)).batch_fingerprint
    baseline=fp()
    assert baseline=="578850d498e6d6e28673e7bd8274138af3266a713bb3d2148d9363189e64ff99"
    changes=(ContradictionSide(claim_id="clm_left",object_key="x",segment_key="s",period_key="p",metric_definition_key="m"),ContradictionSide(claim_id="clm_left",object_key="o",segment_key="x",period_key="p",metric_definition_key="m"),ContradictionSide(claim_id="clm_left",object_key="o",segment_key="s",period_key="x",metric_definition_key="m"),ContradictionSide(claim_id="clm_left",object_key="o",segment_key="s",period_key="p",metric_definition_key="x"))
    assert all(fp(item)!=baseline for item in changes)
    assert fp(right,left)!=baseline
