from dataclasses import fields,FrozenInstanceError
import pytest
from app.module_registry import ModuleResultStatus
from app.marketing_orchestrator.quality_gates import *
from tests.quality_gate_helpers import *

def test_manifest_accounts_for_accepted_failed_and_blocked_results():
    ok=result("res_ok",claims=(claim("clm_ok"),))
    failed=result("res_fail",claims=(),module_status=ModuleResultStatus.FAIL,evidence_sufficiency=EvidenceSufficiency.INSUFFICIENT,failure_reasons={FailureReason.MODULE_DECLARED_FAILURE})
    blocked=result("res_block",claims=(),module_status=ModuleResultStatus.BLOCKED,evidence_sufficiency=EvidenceSufficiency.NOT_ASSESSED,blocking_reasons={BlockingReason.MISSING_CAPABILITY})
    out=QualityGateEvaluator().evaluate(batch(results=(failed,ok,blocked)))
    m=out.synthesis_manifest
    assert m.evaluated_result_ids==("res_block","res_fail","res_ok")
    assert m.accepted_result_ids==("res_ok",);assert m.accepted_claim_ids==("clm_ok",)
    assert {x.reason for x in m.exclusions}=={ExclusionReason.RESULT_FAILED,ExclusionReason.RESULT_BLOCKED}
    with pytest.raises(FrozenInstanceError):m.accepted_result_ids=()
def test_aggregate_and_outputs_have_no_prose_or_public_dump_fields():
    out=QualityGateEvaluator().evaluate(batch())
    forbidden={"summary","reasoning","chain_of_thought","response","raw_result","module_dump","plan"}
    for contract in (BatchEvaluationResult,GateDecision,ContradictionRecord,SynthesisEligibilityManifest,DecisionResult):assert forbidden.isdisjoint(x.name for x in fields(contract))
    assert all(x.batch_id==out.batch_id and x.batch_fingerprint==out.batch_fingerprint for x in out.gate_decisions)
