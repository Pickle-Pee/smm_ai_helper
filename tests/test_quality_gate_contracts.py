from dataclasses import FrozenInstanceError
from datetime import datetime
import math,pytest
from app.marketing_orchestrator.quality_gates import *
from tests.quality_gate_helpers import *

def test_enums_are_closed_and_module_vocab_reused():
    assert [x.value for x in Confidence]==["UNKNOWN","LOW","MEDIUM","HIGH"]
    assert [x.value for x in GateOutcome]==["PASS","PASS_WITH_LIMITATIONS","FAIL","BLOCKED"]
    from app.module_registry import ModuleId as RegistryModuleId
    assert ModuleId is RegistryModuleId

def test_every_closed_enum_has_exact_unique_membership():
    expected={ClaimType:("FACT","OBSERVATION","INFERENCE","HYPOTHESIS","ASSUMPTION","FORECAST","RECOMMENDATION"),EvidenceSourceClass:("FIRST_PARTY","EXTERNAL_PRIMARY","EXTERNAL_SECONDARY","GENERIC_BENCHMARK","SYNTHETIC","UNKNOWN"),ClaimLineageType:("ORIGINAL","REPEATS","REFORMULATES","DERIVES"),AuthorityStatus:("WITHIN_SCOPE","REQUIRES_REVIEW","OUT_OF_SCOPE"),Materiality:("MATERIAL","NON_MATERIAL"),ContradictionState:("UNRESOLVED","PRIORITIZED","INCOMPARABLE"),ExclusionReason:("RESULT_FAILED","RESULT_BLOCKED","UNRESOLVED_CONTRADICTION","CONTRADICTION_PRECEDENCE"),ReplanningDecision:("CONTINUE_CURRENT_PLAN","REPLAN_REQUIRED","STOP","BLOCKED")}
    for cls,values in expected.items():assert tuple(x.value for x in cls)==values and len(cls)==len(set(values))

def test_required_evidence_sufficiency_and_side_field_shape():
    from dataclasses import fields
    assert tuple(x.name for x in fields(ContradictionSide))==("claim_id","evidence_id","object_key","segment_key","period_key","metric_definition_key")
    assert tuple(x.name for x in fields(ContradictionInput))==("contradiction_id","left","right")
    assert tuple(x.name for x in fields(ContradictionRecord))[3:5]==("left","right")
    with pytest.raises(QualityGateContractError):NormalizedModuleResult(result_id="res_x",module_id=ModuleId.VIRTUAL_CMO,module_status=ModuleResultStatus.PASS)
def test_contracts_freeze_sources_and_derived_are_output_only():
    src=[claim()]; r=result(claims=src); src.clear(); assert len(r.claims)==1
    with pytest.raises(FrozenInstanceError):r.result_id="res_other"
    with pytest.raises(QualityGateContractError):
        GateDecision(batch_id="bat_x",batch_fingerprint="0"*64,result_id="res_x",module_id=ModuleId.VIRTUAL_CMO,module_status=ModuleResultStatus.PASS,structural_validity=StructuralValidity.VALID,gate_outcome=GateOutcome.PASS,evidence_sufficiency=EvidenceSufficiency.SUFFICIENT,accepted_claim_ids=(),excluded_claim_ids=(),assumption_ids=(),evidence_ids=(),limitation_ids=(),contradiction_ids=(),failure_reasons=(),blocking_reasons=(),authority_status=AuthorityStatus.WITHIN_SCOPE,synthesis_eligibility=SynthesisEligibility.ELIGIBLE,execution_readiness=ExecutionReadiness.PLANNING_ONLY)
def test_exact_hostile_containers_rejected_without_iteration():
    class Hostile(list):
        def __iter__(self):raise AssertionError
    with pytest.raises(QualityGateContractError):result(claims=Hostile())
def test_ids_scalars_unicode_and_time_boundary():
    for bad in ("clm_A","clm_é","res_wrong",str("clm_")+"a"*64):
        with pytest.raises(QualityGateContractError):claim(bad)
    for bad in (math.inf,math.nan,object()):
        with pytest.raises(QualityGateContractError):claim(value=bad)
    with pytest.raises(QualityGateContractError):claim(value="\ud800")
    with pytest.raises(QualityGateContractError):EvidenceRecord("evd_x",EvidenceSourceClass.UNKNOWN,"p",datetime(2024,1,1))
def test_lineage_contract():
    with pytest.raises(QualityGateContractError):claim(parent_claim_ids=("clm_parent",))
    assert claim(lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=("clm_parent",)).parent_claim_ids==("clm_parent",)
