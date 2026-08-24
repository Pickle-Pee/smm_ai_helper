import pytest
from app.marketing_orchestrator.quality_gates import *
from tests.quality_gate_helpers import *
def _gate(r=result()):return QualityGateEvaluator().evaluate(batch(results=(r,))).gate_decisions[0]
@pytest.mark.parametrize("kwargs,decision",[
 ({},ReplanningDecision.CONTINUE_CURRENT_PLAN),
 ({"stop_reasons":{StopReason.SUFFICIENT_EVIDENCE}},ReplanningDecision.STOP),
 ({"replan_reasons":{ReplanReason.MATERIAL_FINDING}},ReplanningDecision.REPLAN_REQUIRED),
 ({"stop_reasons":{StopReason.DIMINISHING_VALUE}},ReplanningDecision.STOP),
 ({"replan_reasons":{ReplanReason.MATERIAL_FINDING},"stop_reasons":{StopReason.SCOPE_COMPLETE}},ReplanningDecision.STOP)])
def test_accepted_decision_precedence(kwargs,decision):
    g=_gate();assert DecisionEvaluator.evaluate(DecisionRequest(g.batch_id,g.batch_fingerprint,g,**kwargs)).decision is decision
def test_failed_and_blocked_compatibility():
    f=_gate(result(claims=(),module_status=ModuleResultStatus.FAIL,evidence_sufficiency=EvidenceSufficiency.INSUFFICIENT,failure_reasons={FailureReason.MODULE_DECLARED_FAILURE}))
    assert DecisionEvaluator.evaluate(DecisionRequest(f.batch_id,f.batch_fingerprint,f,stop_reasons={StopReason.RESULT_FAILED})).decision is ReplanningDecision.STOP
    b=_gate(result(claims=(),module_status=ModuleResultStatus.BLOCKED,evidence_sufficiency=EvidenceSufficiency.NOT_ASSESSED,blocking_reasons={BlockingReason.MISSING_CAPABILITY}))
    assert DecisionEvaluator.evaluate(DecisionRequest(b.batch_id,b.batch_fingerprint,b,blocking_reasons={BlockingReason.MISSING_CAPABILITY})).decision is ReplanningDecision.BLOCKED
    with pytest.raises(QualityGateContractError):DecisionEvaluator.evaluate(DecisionRequest(b.batch_id,b.batch_fingerprint,b))
def test_cross_stage_identity_rejected():
    g=_gate()
    with pytest.raises(QualityGateContractError):DecisionRequest(g.batch_id,"0"*64,g)

def test_incompatible_accepted_and_failed_triggers_rejected():
    g=_gate()
    with pytest.raises(QualityGateContractError):DecisionEvaluator.evaluate(DecisionRequest(g.batch_id,g.batch_fingerprint,g,stop_reasons={StopReason.RESULT_FAILED}))
    f=_gate(result(claims=(),module_status=ModuleResultStatus.FAIL,evidence_sufficiency=EvidenceSufficiency.INSUFFICIENT,failure_reasons={FailureReason.MODULE_DECLARED_FAILURE}))
    with pytest.raises(QualityGateContractError):DecisionEvaluator.evaluate(DecisionRequest(f.batch_id,f.batch_fingerprint,f,replan_reasons={ReplanReason.MATERIAL_FINDING},stop_reasons={StopReason.RESULT_FAILED}))
