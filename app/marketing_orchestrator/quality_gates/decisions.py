from .contracts import *
from .errors import QualityGateContractError

class DecisionEvaluator:
    @staticmethod
    def evaluate(req:DecisionRequest)->DecisionResult:
        g=req.gate_decision
        rr=tuple(sorted(req.replan_reasons,key=lambda x:x.value)); sr=tuple(sorted(req.stop_reasons,key=lambda x:x.value)); br=tuple(sorted(req.blocking_reasons,key=lambda x:x.value))
        if g.gate_outcome is GateOutcome.BLOCKED:
            if rr or sr or frozenset(br)!=frozenset(g.blocking_reasons):raise QualityGateContractError("BLOCKED decision requires exactly matching blocking reasons")
            d=ReplanningDecision.BLOCKED; selected=((),(),br)
        elif g.gate_outcome is GateOutcome.FAIL:
            if rr or br or frozenset(sr)!={StopReason.RESULT_FAILED}:raise QualityGateContractError("FAIL decision requires exactly RESULT_FAILED")
            d=ReplanningDecision.STOP; selected=((),sr,())
        else:
            if br:raise QualityGateContractError("accepted decision forbids blocking reasons")
            if StopReason.RESULT_FAILED in sr:raise QualityGateContractError("accepted decision forbids RESULT_FAILED")
            terminal=tuple(x for x in sr if x in (StopReason.SCOPE_COMPLETE,StopReason.SUFFICIENT_EVIDENCE))
            lower=tuple(x for x in sr if x not in terminal)
            if terminal:d=ReplanningDecision.STOP;selected=((),terminal,())
            elif rr:d=ReplanningDecision.REPLAN_REQUIRED;selected=(rr,(),())
            elif lower:d=ReplanningDecision.STOP;selected=((),lower,())
            else:d=ReplanningDecision.CONTINUE_CURRENT_PLAN;selected=((),(),())
        return DecisionResult._make(batch_id=req.batch_id,batch_fingerprint=req.batch_fingerprint,result_id=g.result_id,gate_outcome=g.gate_outcome,decision=d,replan_reasons=selected[0],stop_reasons=selected[1],blocking_reasons=selected[2],execution_readiness=ExecutionReadiness.PLANNING_ONLY)
