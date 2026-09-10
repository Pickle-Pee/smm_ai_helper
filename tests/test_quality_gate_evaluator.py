from dataclasses import FrozenInstanceError
import pytest
from app.module_registry import ModuleResultStatus
from app.marketing_orchestrator.quality_gates import *
from tests.quality_gate_helpers import *

@pytest.mark.parametrize("r,out",[
 (result(),GateOutcome.PASS),
 (result(module_status=ModuleResultStatus.PASS_WITH_LIMITATIONS,evidence_sufficiency=EvidenceSufficiency.LIMITED,limitations=(LimitationRecord("lim_one",LimitationReason.TOOL_LIMIT,Materiality.MATERIAL,("res_one",)),)),GateOutcome.PASS_WITH_LIMITATIONS),
 (result(claims=(),module_status=ModuleResultStatus.FAIL,evidence_sufficiency=EvidenceSufficiency.INSUFFICIENT,failure_reasons={FailureReason.MODULE_DECLARED_FAILURE}),GateOutcome.FAIL),
 (result(claims=(),module_status=ModuleResultStatus.BLOCKED,evidence_sufficiency=EvidenceSufficiency.NOT_ASSESSED,blocking_reasons={BlockingReason.MISSING_CAPABILITY}),GateOutcome.BLOCKED)])
def test_legal_gate_matrix(r,out):assert QualityGateEvaluator().evaluate(batch(results=(r,))).gate_decisions[0].gate_outcome is out
@pytest.mark.parametrize("r",[
 result(claims=()),
 result(limitations=(LimitationRecord("lim_one",LimitationReason.TOOL_LIMIT,Materiality.MATERIAL,("res_one",)),)),
 result(module_status=ModuleResultStatus.PASS_WITH_LIMITATIONS),
 result(evidence_sufficiency=EvidenceSufficiency.INSUFFICIENT)])
def test_illegal_gate_matrix(r):
    with pytest.raises(QualityGateContractError):QualityGateEvaluator().evaluate(batch(results=(r,)))
def test_registry_output_handoff_and_confidence_validation():
    with pytest.raises(QualityGateContractError):QualityGateEvaluator().evaluate(batch(results=(result(claims=(claim(declared_output_name="unknown"),)),)))
    with pytest.raises(QualityGateContractError):QualityGateEvaluator().evaluate(batch(results=(result(handoff_module_ids={ModuleId.MENTOR}),)))
    parent=claim("clm_parent",confidence=Confidence.LOW); child=claim("clm_child",confidence=Confidence.HIGH,lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=("clm_parent",))
    with pytest.raises(QualityGateContractError):QualityGateEvaluator().evaluate(batch(results=(result(claims=(parent,child)),)))
def test_result_is_deterministic_planning_only_and_manifest_frozen():
    a=QualityGateEvaluator().evaluate(batch());b=QualityGateEvaluator().evaluate(batch());assert a==b
    assert a.execution_readiness is ExecutionReadiness.PLANNING_ONLY
    with pytest.raises(FrozenInstanceError):a.synthesis_manifest.batch_id="bat_x"

def test_derived_id_collision_is_contained(monkeypatch):
    left=ContradictionSide(claim_id="clm_left",object_key="o",segment_key="s",period_key="p",metric_definition_key="m");right=ContradictionSide(claim_id="clm_right",object_key="o",segment_key="s",period_key="p",metric_definition_key="m")
    b=batch(results=(result(claims=(claim("clm_left"),claim("clm_right"))),),contradictions=(ContradictionInput("ctr_one",left,right),))
    class Digest:
        def hexdigest(self):return "0"*64
    monkeypatch.setattr("app.marketing_orchestrator.quality_gates.evaluator.derive_id",lambda prefix,components:(prefix+"_"+"0"*32,"|".join(components).encode()))
    with pytest.raises(QualityGateContractError,match="collision"):QualityGateEvaluator().evaluate(b)
