from collections.abc import Mapping, Sequence, Set
from dataclasses import MISSING, FrozenInstanceError, fields, replace
from datetime import timedelta

import pytest

from app.marketing_orchestrator.quality_gates import *
from tests.quality_gate_helpers import UTC, batch, claim, result


def _side(claim_id="clm_left"):
    return ContradictionSide(
        claim_id=claim_id,
        object_key="object",
        segment_key="segment",
        period_key="period",
        metric_definition_key="metric",
    )


CALLER_CONTRACTS = (
    (EvidenceRecord, ("evd_one", EvidenceSourceClass.FIRST_PARTY, "source"), {}),
    (AssumptionRecord, ("asm_one", "assumption", Materiality.MATERIAL), {}),
    (LimitationRecord, ("lim_one", LimitationReason.TOOL_LIMIT, Materiality.MATERIAL, ("res_one",)), {}),
    (NormalizedClaim, ("clm_one", "strategic_diagnosis", ClaimType.FACT, Confidence.HIGH, AuthorityStatus.WITHIN_SCOPE, "value", ClaimLineageType.ORIGINAL), {}),
    (NormalizedModuleResult, (), {"result_id":"res_one", "module_id":ModuleId.VIRTUAL_CMO, "module_status":ModuleResultStatus.PASS, "evidence_sufficiency":EvidenceSufficiency.SUFFICIENT}),
    (ContradictionSide, (), {"claim_id":"clm_left", "object_key":"object", "segment_key":"segment", "period_key":"period", "metric_definition_key":"metric"}),
    (ContradictionInput, ("ctr_one", _side(), _side("clm_right")), {}),
    (EvaluationBatch, ("bat_one", (result(),)), {}),
    (DecisionRequest, (), None),
)


def _construction_case(cls, args, kwargs):
    if cls is DecisionRequest:
        gate=QualityGateEvaluator().evaluate(batch()).gate_decisions[0]
        return (), {"batch_id":gate.batch_id, "batch_fingerprint":gate.batch_fingerprint, "gate_decision":gate}
    return args, dict(kwargs)


@pytest.mark.parametrize("cls,args,kwargs", CALLER_CONTRACTS)
def test_controlled_construction_matrix(cls, args, kwargs):
    args, kwargs=_construction_case(cls,args,kwargs)
    assert type(cls(*args,**kwargs)) is cls
    required=next(f for f in fields(cls) if f.init and f.default is MISSING and f.default_factory is MISSING)
    position=next((i for i,f in enumerate(fields(cls)) if f.name==required.name and i<len(args)),None)
    if position is None:
        missing=dict(kwargs);missing.pop(required.name,None)
        missing_args=args
    else:
        missing_args=args[:position]+args[position+1:];missing=dict(kwargs)
    with pytest.raises(QualityGateContractError):cls(*missing_args,**missing)
    with pytest.raises(QualityGateContractError):cls(*args,**kwargs,unknown_field=True)
    if args:
        first=next(f for f in fields(cls) if f.init and not f.kw_only)
        with pytest.raises(QualityGateContractError):cls(*args,**kwargs,**{first.name:args[0]})
    else:
        with pytest.raises(QualityGateContractError):cls(object())


def test_derived_field_injection_and_output_construction_are_controlled():
    with pytest.raises(QualityGateContractError):
        EvaluationBatch("bat_one",(result(),),batch_fingerprint="0"*64)
    with pytest.raises(QualityGateContractError):
        PropagatedClaimContext(batch_id="bat_one",batch_fingerprint="0"*64,claim_id="clm_one",effective_confidence=Confidence.HIGH)


def test_controlled_boundary_does_not_swallow_internal_programming_errors(monkeypatch):
    def broken(_self):raise TypeError("programmer defect")
    monkeypatch.setattr(EvidenceRecord,"__post_init__",broken)
    with pytest.raises(TypeError,match="programmer defect"):
        EvidenceRecord("evd_one",EvidenceSourceClass.UNKNOWN,"source")


def _lineage_batch(*, materiality=Materiality.MATERIAL, parent_order=("clm_left","clm_right"), child_confidence=Confidence.LOW):
    evidence=(EvidenceRecord("evd_parent",EvidenceSourceClass.FIRST_PARTY,"source",UTC),)
    assumptions=(AssumptionRecord("asm_parent","assumption",Materiality.MATERIAL),)
    limitation=LimitationRecord("lim_parent",LimitationReason.TOOL_LIMIT,materiality,("res_parent",),("clm_left",))
    left=claim("clm_left",confidence=Confidence.MEDIUM,evidence_ids=("evd_parent",),assumption_ids=("asm_parent",),limitation_ids=("lim_parent",))
    right=claim("clm_right",confidence=Confidence.HIGH)
    parent=result("res_parent",claims=(left,right),evidence=evidence,assumptions=assumptions,limitations=(limitation,),module_status=ModuleResultStatus.PASS_WITH_LIMITATIONS if materiality is Materiality.MATERIAL else ModuleResultStatus.PASS,evidence_sufficiency=EvidenceSufficiency.LIMITED if materiality is Materiality.MATERIAL else EvidenceSufficiency.SUFFICIENT)
    child=result("res_child",claims=(claim("clm_child",confidence=child_confidence,lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=parent_order),))
    return EvaluationBatch("bat_lineage",(child,parent))


def test_evaluator_integrates_recursive_propagation_into_context_decision_and_manifest():
    out=QualityGateEvaluator().evaluate(_lineage_batch())
    contexts={x.claim_id:x for x in out.propagated_claim_contexts}
    child=contexts["clm_child"]
    assert child.evidence_ids==("evd_parent",)
    assert child.assumption_ids==("asm_parent",)
    assert child.limitation_ids==("lim_parent",)
    assert child.effective_confidence is Confidence.LOW
    decision={x.result_id:x for x in out.gate_decisions}["res_child"]
    assert decision.evidence_ids==("evd_parent",)
    assert decision.assumption_ids==("asm_parent",)
    assert decision.limitation_ids==("lim_parent",)
    assert decision.gate_outcome is GateOutcome.PASS_WITH_LIMITATIONS
    assert "lim_parent" in out.synthesis_manifest.limitation_ids
    assert all((x.batch_id,x.batch_fingerprint)==(out.batch_id,out.batch_fingerprint) for x in out.propagated_claim_contexts)
    with pytest.raises(FrozenInstanceError):child.evidence_ids=()


def test_non_material_multi_level_diamond_is_order_independent_and_idempotent():
    one=_lineage_batch(materiality=Materiality.NON_MATERIAL)
    two=_lineage_batch(materiality=Materiality.NON_MATERIAL,parent_order=("clm_right","clm_left"))
    out_one=QualityGateEvaluator().evaluate(one);out_repeat=QualityGateEvaluator().evaluate(one);out_two=QualityGateEvaluator().evaluate(two)
    assert out_one==out_repeat
    c1={x.claim_id:x for x in out_one.propagated_claim_contexts}["clm_child"]
    c2={x.claim_id:x for x in out_two.propagated_claim_contexts}["clm_child"]
    assert (c1.evidence_ids,c1.assumption_ids,c1.limitation_ids,c1.effective_confidence)==(c2.evidence_ids,c2.assumption_ids,c2.limitation_ids,c2.effective_confidence)

    root=claim("clm_root",confidence=Confidence.MEDIUM)
    left=claim("clm_a",confidence=Confidence.MEDIUM,lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=("clm_root",))
    right=claim("clm_b",confidence=Confidence.LOW,lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=("clm_root",))
    leaf=claim("clm_leaf",confidence=Confidence.LOW,lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=("clm_a","clm_b"))
    diamond=QualityGateEvaluator().evaluate(batch(results=(result(claims=(leaf,right,root,left)),)))
    assert {x.claim_id:x.effective_confidence for x in diamond.propagated_claim_contexts}["clm_leaf"] is Confidence.LOW

    evidence=EvidenceRecord("evd_root",EvidenceSourceClass.EXTERNAL_PRIMARY,"root",UTC)
    assumption=AssumptionRecord("asm_root","root",Materiality.NON_MATERIAL)
    limitation=LimitationRecord("lim_root",LimitationReason.INCOMPLETE_COVERAGE,Materiality.NON_MATERIAL,("res_chain",))
    root=claim("clm_root",confidence=Confidence.MEDIUM,evidence_ids=("evd_root",),assumption_ids=("asm_root",),limitation_ids=("lim_root",))
    middle=claim("clm_middle",confidence=Confidence.LOW,lineage_type=ClaimLineageType.REFORMULATES,parent_claim_ids=("clm_root",))
    leaf=claim("clm_leaf",confidence=Confidence.LOW,lineage_type=ClaimLineageType.REPEATS,parent_claim_ids=("clm_middle",))
    source_claims=[root,middle,leaf]
    chain_batch=batch(results=(result("res_chain",claims=source_claims,evidence=(evidence,),assumptions=(assumption,),limitations=(limitation,)),))
    chain=QualityGateEvaluator().evaluate(chain_batch)
    source_claims.clear()
    effective={x.claim_id:x for x in chain.propagated_claim_contexts}["clm_leaf"]
    assert (effective.evidence_ids,effective.assumption_ids,effective.limitation_ids)==(("evd_root",),("asm_root",),("lim_root",))
    assert len(chain_batch.results[0].claims)==3


@pytest.mark.parametrize("claims",[
    (claim("clm_self",lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=("clm_self",)),),
    (claim("clm_a",lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=("clm_b",)),claim("clm_b",lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=("clm_a",))),
    (claim("clm_a",lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=("clm_b",)),claim("clm_b",lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=("clm_c",)),claim("clm_c",lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=("clm_a",))),
])
def test_lineage_cycles_are_rejected(claims):
    with pytest.raises(QualityGateContractError,match="cycle"):
        QualityGateEvaluator().evaluate(batch(results=(result(claims=claims),)))


def test_conflicting_batch_record_identity_is_rejected_before_propagation():
    first=result("res_a",claims=(claim("clm_a",assumption_ids=("asm_same",)),),assumptions=(AssumptionRecord("asm_same","one",Materiality.MATERIAL),))
    second=result("res_b",claims=(claim("clm_b"),),assumptions=(AssumptionRecord("asm_same","changed",Materiality.MATERIAL),))
    with pytest.raises(QualityGateContractError,match="duplicate assumption ID"):
        QualityGateEvaluator().evaluate(batch(results=(first,second)))


def test_mixed_decision_retains_every_evaluated_trigger():
    gate=QualityGateEvaluator().evaluate(batch()).gate_decisions[0]
    request=DecisionRequest(gate.batch_id,gate.batch_fingerprint,gate,replan_reasons={ReplanReason.MATERIAL_FINDING},stop_reasons={StopReason.SCOPE_COMPLETE,StopReason.DIMINISHING_VALUE})
    first=DecisionEvaluator.evaluate(request);second=DecisionEvaluator.evaluate(request)
    assert first==second
    assert first.decision is ReplanningDecision.STOP
    assert first.replan_reasons==(ReplanReason.MATERIAL_FINDING,)
    assert first.stop_reasons==(StopReason.DIMINISHING_VALUE,StopReason.SCOPE_COMPLETE)
    reordered=DecisionRequest(gate.batch_id,gate.batch_fingerprint,gate,replan_reasons=frozenset({ReplanReason.MATERIAL_FINDING}),stop_reasons=frozenset({StopReason.DIMINISHING_VALUE,StopReason.SCOPE_COMPLETE}))
    assert DecisionEvaluator.evaluate(reordered)==first
    with pytest.raises(QualityGateContractError):
        DecisionRequest(gate.batch_id,gate.batch_fingerprint,gate,replan_reasons=[ReplanReason.MATERIAL_FINDING,ReplanReason.MATERIAL_FINDING])


def test_multiple_reasons_within_each_tier_are_retained_in_normative_order():
    gate=QualityGateEvaluator().evaluate(batch()).gate_decisions[0]
    replan={ReplanReason.REVERSIBLE_TEST_HIGHER_VALUE,ReplanReason.DEPENDENCY_INVALIDATED}
    lower={StopReason.TOOL_LIMIT_REACHED,StopReason.CAPABILITY_LIMIT_REACHED}
    replanned=DecisionEvaluator.evaluate(DecisionRequest(gate.batch_id,gate.batch_fingerprint,gate,replan_reasons=replan,stop_reasons=lower))
    assert replanned.decision is ReplanningDecision.REPLAN_REQUIRED
    assert replanned.replan_reasons==tuple(sorted(replan,key=lambda x:x.value))
    assert replanned.stop_reasons==tuple(sorted(lower,key=lambda x:x.value))
    terminal={StopReason.SUFFICIENT_EVIDENCE,StopReason.SCOPE_COMPLETE}
    stopped=DecisionEvaluator.evaluate(DecisionRequest(gate.batch_id,gate.batch_fingerprint,gate,replan_reasons=replan,stop_reasons=terminal|lower))
    assert stopped.decision is ReplanningDecision.STOP
    assert stopped.replan_reasons==tuple(sorted(replan,key=lambda x:x.value))
    assert stopped.stop_reasons==tuple(sorted(terminal|lower,key=lambda x:x.value))


ENUM_MEMBERS = {
    ClaimType:("FACT","OBSERVATION","INFERENCE","HYPOTHESIS","ASSUMPTION","FORECAST","RECOMMENDATION"),
    Confidence:("UNKNOWN","LOW","MEDIUM","HIGH"), GateOutcome:("PASS","PASS_WITH_LIMITATIONS","FAIL","BLOCKED"),
    StructuralValidity:("VALID",), ExecutionReadiness:("PLANNING_ONLY",), SynthesisEligibility:("ELIGIBLE","INELIGIBLE"),
    EvidenceSufficiency:("SUFFICIENT","LIMITED","INSUFFICIENT","NOT_ASSESSED"),
    EvidenceSourceClass:("FIRST_PARTY","EXTERNAL_PRIMARY","EXTERNAL_SECONDARY","GENERIC_BENCHMARK","SYNTHETIC","UNKNOWN"),
    ClaimLineageType:("ORIGINAL","REPEATS","REFORMULATES","DERIVES"), Materiality:("MATERIAL","NON_MATERIAL"),
    AuthorityStatus:("WITHIN_SCOPE","REQUIRES_REVIEW","OUT_OF_SCOPE"),
    LimitationReason:("MISSING_PREFERRED_INPUT","INCOMPLETE_COVERAGE","INSUFFICIENT_EVIDENCE","STALE_EVIDENCE","TOOL_LIMIT","CAPABILITY_LIMIT","ASSUMPTION_DEPENDENCY","UNRESOLVED_CONTRADICTION","OUT_OF_SCOPE"),
    FailureReason:("MODULE_DECLARED_FAILURE","NO_USABLE_CLAIMS","INSUFFICIENT_EVIDENCE","DECLARED_OUTPUT_MISSING","AUTHORITY_VIOLATION"),
    BlockingReason:("MISSING_BLOCKING_INPUT","MISSING_CAPABILITY","TOOL_UNAVAILABLE","DEPENDENCY_BLOCKED","AUTHORIZATION_REQUIRED"),
    ContradictionState:("UNRESOLVED","PRIORITIZED","INCOMPARABLE"), ContradictionPrecedenceReason:("FIRST_PARTY_NOT_OLDER_THAN_BENCHMARK",),
    FreshnessComparison:("NEWER","OLDER","SAME","UNKNOWN"), ExclusionReason:("RESULT_FAILED","RESULT_BLOCKED","UNRESOLVED_CONTRADICTION","CONTRADICTION_PRECEDENCE"),
    ExclusionSubjectType:("RESULT","CLAIM"), ReplanningDecision:("CONTINUE_CURRENT_PLAN","REPLAN_REQUIRED","STOP","BLOCKED"),
    ReplanReason:("MATERIAL_FINDING","DEPENDENCY_INVALIDATED","REVERSIBLE_TEST_HIGHER_VALUE"),
    StopReason:("SCOPE_COMPLETE","SUFFICIENT_EVIDENCE","DIMINISHING_VALUE","TOOL_LIMIT_REACHED","CAPABILITY_LIMIT_REACHED","RESULT_FAILED"),
}


def test_every_closed_enum_has_independently_declared_exact_names_and_values():
    for enum, expected in ENUM_MEMBERS.items():
        assert tuple(enum.__members__)==expected
        assert tuple(member.value for member in enum)==expected


class _HostileMixin:
    calls=0
    @classmethod
    def hit(cls):cls.calls+=1;raise AssertionError("hostile operation")
    def __iter__(self):return self.hit()
    def __eq__(self,_):return self.hit()
    def __len__(self):return self.hit()
    def __getitem__(self,_):return self.hit()
    def __copy__(self):return self.hit()
    def __repr__(self):return self.hit()
    def __str__(self):return self.hit()
    def __hash__(self):return self.hit()
    def __contains__(self,_):return self.hit()
    def __int__(self):return self.hit()
    def __float__(self):return self.hit()
    def __reduce__(self):return self.hit()

class HostileStr(_HostileMixin,str):pass
class HostileInt(_HostileMixin,int):pass
class HostileFloat(_HostileMixin,float):pass
class HostileList(_HostileMixin,list):pass
class HostileTuple(_HostileMixin,tuple):pass
class HostileDict(_HostileMixin,dict):pass
class HostileSet(_HostileMixin,set):pass
class HostileFrozenSet(_HostileMixin,frozenset):pass
class HostileMapping(_HostileMixin,Mapping):pass
class HostileSequence(_HostileMixin,Sequence):pass
class HostileAbstractSet(_HostileMixin,Set):pass

@pytest.mark.parametrize("value,make",[
    (HostileStr("x"),lambda x:claim(value=x)),(HostileInt(1),lambda x:claim(value=x)),(HostileFloat(1),lambda x:claim(value=x)),
    (HostileList(),lambda x:result(claims=x)),(HostileTuple(),lambda x:result(claims=x)),(HostileDict(),lambda x:claim(value=x)),
    (HostileSet(),lambda x:result(failure_reasons=x)),(HostileFrozenSet(),lambda x:result(failure_reasons=x)),
    (HostileMapping(),lambda x:claim(value=x)),(HostileSequence(),lambda x:result(claims=x)),(HostileAbstractSet(),lambda x:result(failure_reasons=x)),
],ids=("str","int","float","list","tuple","dict","set","frozenset","mapping","sequence","abstract-set"))
def test_complete_hostile_type_families_are_rejected_without_operations(value,make):
    type(value).calls=0
    with pytest.raises(QualityGateContractError):make(value)
    assert type(value).calls==0


def test_nested_hostile_value_is_rejected_before_operations():
    hostile=HostileStr("clm_hostile");HostileStr.calls=0
    with pytest.raises(QualityGateContractError):
        claim(parent_claim_ids=(hostile,),lineage_type=ClaimLineageType.DERIVES)
    assert HostileStr.calls==0


FINGERPRINT_SOURCE_FIELDS = (
    "batch.batch_id","batch.evaluation_at","batch.results","batch.contradictions",
    "result.result_id","result.module_id","result.module_status","result.claims","result.evidence","result.assumptions","result.limitations","result.failure_reasons","result.blocking_reasons","result.evidence_sufficiency","result.handoff_module_ids",
    "claim.claim_id","claim.declared_output_name","claim.claim_type","claim.confidence","claim.authority_status","claim.value","claim.lineage_type","claim.parent_claim_ids","claim.evidence_ids","claim.assumption_ids","claim.limitation_ids",
    "evidence.evidence_id","evidence.source_class","evidence.provenance","evidence.observed_at",
    "assumption.assumption_id","assumption.description","assumption.materiality",
    "limitation.limitation_id","limitation.reason","limitation.materiality","limitation.related_result_ids","limitation.related_claim_ids","limitation.related_contradiction_ids","limitation.description",
    "contradiction.contradiction_id","contradiction.left","contradiction.right",
    "side.claim_id","side.evidence_id","side.object_key","side.segment_key","side.period_key","side.metric_definition_key",
)


def _fingerprint_fixture():
    ev=EvidenceRecord("evd_one",EvidenceSourceClass.FIRST_PARTY,"source",UTC)
    asm=AssumptionRecord("asm_one","assumption",Materiality.MATERIAL)
    lim=LimitationRecord("lim_one",LimitationReason.TOOL_LIMIT,Materiality.MATERIAL,("res_one",),("clm_left",),("ctr_one",),"limit")
    left_claim=claim("clm_left",confidence=Confidence.LOW,lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=("clm_right",),evidence_ids=("evd_one",),assumption_ids=("asm_one",),limitation_ids=("lim_one",))
    right_claim=claim("clm_right")
    alternate_parent=claim("clm_alternate")
    r=result("res_one",claims=(left_claim,right_claim,alternate_parent),evidence=(ev,),assumptions=(asm,),limitations=(lim,),failure_reasons={FailureReason.MODULE_DECLARED_FAILURE},blocking_reasons={BlockingReason.MISSING_CAPABILITY},handoff_module_ids={ModuleId.MENTOR})
    left=ContradictionSide(claim_id="clm_left",evidence_id="evd_one",object_key="object",segment_key="segment",period_key="period",metric_definition_key="metric")
    right=ContradictionSide(claim_id="clm_right",evidence_id="evd_one",object_key="object",segment_key="segment",period_key="period",metric_definition_key="metric")
    return EvaluationBatch("bat_matrix",(r,),(ContradictionInput("ctr_one",left,right),),UTC)


def test_independent_fingerprint_participation_matrix_and_derived_exclusions():
    base=_fingerprint_fixture();r=base.results[0];c=base.contradictions[0];left=c.left;right=c.right;clm=r.claims[0];ev=r.evidence[0];asm=r.assumptions[0];lim=r.limitations[0]
    def with_result(new):return replace(base,results=(new,))
    def with_claim(new):return with_result(replace(r,claims=(new,*r.claims[1:])))
    def with_side(new_left=left,new_right=right):return replace(base,contradictions=(replace(c,left=new_left,right=new_right),))
    mutations={
        "batch.batch_id":replace(base,batch_id="bat_other"),"batch.evaluation_at":replace(base,evaluation_at=UTC+timedelta(seconds=1)),"batch.results":replace(base,results=(replace(r,result_id="res_other"),)),"batch.contradictions":replace(base,contradictions=()),
        "result.result_id":with_result(replace(r,result_id="res_other")),"result.module_id":with_result(replace(r,module_id=ModuleId.MENTOR)),"result.module_status":with_result(replace(r,module_status=ModuleResultStatus.FAIL)),"result.claims":with_result(replace(r,claims=(r.claims[0],))),"result.evidence":with_result(replace(r,evidence=())),"result.assumptions":with_result(replace(r,assumptions=())),"result.limitations":with_result(replace(r,limitations=())),"result.failure_reasons":with_result(replace(r,failure_reasons=frozenset())),"result.blocking_reasons":with_result(replace(r,blocking_reasons=frozenset())),"result.evidence_sufficiency":with_result(replace(r,evidence_sufficiency=EvidenceSufficiency.LIMITED)),"result.handoff_module_ids":with_result(replace(r,handoff_module_ids=frozenset())),
        "claim.claim_id":with_claim(replace(clm,claim_id="clm_other")),"claim.declared_output_name":with_claim(replace(clm,declared_output_name="other")),"claim.claim_type":with_claim(replace(clm,claim_type=ClaimType.INFERENCE)),"claim.confidence":with_claim(replace(clm,confidence=Confidence.UNKNOWN)),"claim.authority_status":with_claim(replace(clm,authority_status=AuthorityStatus.REQUIRES_REVIEW)),"claim.value":with_claim(replace(clm,value="other")),"claim.lineage_type":with_claim(replace(clm,lineage_type=ClaimLineageType.REFORMULATES)),"claim.parent_claim_ids":with_claim(replace(clm,parent_claim_ids=("clm_alternate",))),"claim.evidence_ids":with_claim(replace(clm,evidence_ids=())),"claim.assumption_ids":with_claim(replace(clm,assumption_ids=())),"claim.limitation_ids":with_claim(replace(clm,limitation_ids=())),
        "evidence.evidence_id":with_result(replace(r,evidence=(replace(ev,evidence_id="evd_other"),))),"evidence.source_class":with_result(replace(r,evidence=(replace(ev,source_class=EvidenceSourceClass.UNKNOWN),))),"evidence.provenance":with_result(replace(r,evidence=(replace(ev,provenance="other"),))),"evidence.observed_at":with_result(replace(r,evidence=(replace(ev,observed_at=UTC+timedelta(seconds=1)),))),
        "assumption.assumption_id":with_result(replace(r,assumptions=(replace(asm,assumption_id="asm_other"),))),"assumption.description":with_result(replace(r,assumptions=(replace(asm,description="other"),))),"assumption.materiality":with_result(replace(r,assumptions=(replace(asm,materiality=Materiality.NON_MATERIAL),))),
        "limitation.limitation_id":with_result(replace(r,limitations=(replace(lim,limitation_id="lim_other"),))),"limitation.reason":with_result(replace(r,limitations=(replace(lim,reason=LimitationReason.CAPABILITY_LIMIT),))),"limitation.materiality":with_result(replace(r,limitations=(replace(lim,materiality=Materiality.NON_MATERIAL),))),"limitation.related_result_ids":with_result(replace(r,limitations=(replace(lim,related_result_ids=("res_other",)),))),"limitation.related_claim_ids":with_result(replace(r,limitations=(replace(lim,related_claim_ids=("clm_right",)),))),"limitation.related_contradiction_ids":with_result(replace(r,limitations=(replace(lim,related_contradiction_ids=()),))),"limitation.description":with_result(replace(r,limitations=(replace(lim,description="other"),))),
        "contradiction.contradiction_id":replace(base,contradictions=(replace(c,contradiction_id="ctr_other"),)),"contradiction.left":with_side(replace(left,object_key="other")),"contradiction.right":with_side(new_right=replace(right,object_key="other")),
        "side.claim_id":with_side(replace(left,claim_id="clm_other")),"side.evidence_id":with_side(replace(left,evidence_id=None)),"side.object_key":with_side(replace(left,object_key="other")),"side.segment_key":with_side(replace(left,segment_key="other")),"side.period_key":with_side(replace(left,period_key="other")),"side.metric_definition_key":with_side(replace(left,metric_definition_key="other")),
    }
    assert tuple(mutations)==FINGERPRINT_SOURCE_FIELDS
    assert all(item.batch_fingerprint!=base.batch_fingerprint for item in mutations.values())
    assert replace(base,contradictions=(replace(c,left=right,right=left),)).batch_fingerprint!=base.batch_fingerprint
    out=QualityGateEvaluator().evaluate(batch())
    assert out.batch_fingerprint==out.gate_decisions[0].batch_fingerprint
    assert "propagated_claim_contexts" not in FINGERPRINT_SOURCE_FIELDS
    assert "batch_fingerprint" not in FINGERPRINT_SOURCE_FIELDS


def test_lineage_fingerprint_fields_are_isolated_with_valid_non_root_claims():
    parent_a=claim("clm_parent_a",confidence=Confidence.MEDIUM)
    parent_b=claim("clm_parent_b",confidence=Confidence.MEDIUM)
    child=claim("clm_child",confidence=Confidence.LOW,lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=("clm_parent_a",))
    def fingerprint(current):
        return EvaluationBatch("bat_lineage_fp",(result(claims=(parent_a,parent_b,current)),)).batch_fingerprint
    baseline=fingerprint(child)
    lineage_only=replace(child,lineage_type=ClaimLineageType.REFORMULATES)
    parent_only=replace(child,parent_claim_ids=("clm_parent_b",))
    assert lineage_only.parent_claim_ids==child.parent_claim_ids
    assert parent_only.lineage_type is child.lineage_type
    assert fingerprint(lineage_only)!=baseline
    assert fingerprint(parent_only)!=baseline


def test_fingerprint_order_rules_use_two_distinct_elements():
    result_a=result("res_a",claims=(claim("clm_a"),))
    result_b=result("res_b",claims=(claim("clm_b"),))
    forward=EvaluationBatch("bat_order",(result_a,result_b))
    reverse=EvaluationBatch("bat_order",(result_b,result_a))
    assert forward.batch_fingerprint==reverse.batch_fingerprint

    evidence=(EvidenceRecord("evd_a",EvidenceSourceClass.FIRST_PARTY,"a",UTC),EvidenceRecord("evd_b",EvidenceSourceClass.UNKNOWN,"b",UTC))
    assumptions=(AssumptionRecord("asm_a","a",Materiality.MATERIAL),AssumptionRecord("asm_b","b",Materiality.NON_MATERIAL))
    limitations=(LimitationRecord("lim_a",LimitationReason.TOOL_LIMIT,Materiality.NON_MATERIAL,("res_order",)),LimitationRecord("lim_b",LimitationReason.CAPABILITY_LIMIT,Materiality.NON_MATERIAL,("res_order",)))
    claims=(claim("clm_a"),claim("clm_b"))
    ordered=result("res_order",claims=claims,evidence=evidence,assumptions=assumptions,limitations=limitations,failure_reasons=[FailureReason.AUTHORITY_VIOLATION,FailureReason.MODULE_DECLARED_FAILURE],handoff_module_ids=[ModuleId.MENTOR,ModuleId.POSITIONING])
    reordered=result("res_order",claims=tuple(reversed(claims)),evidence=tuple(reversed(evidence)),assumptions=tuple(reversed(assumptions)),limitations=tuple(reversed(limitations)),failure_reasons=[FailureReason.MODULE_DECLARED_FAILURE,FailureReason.AUTHORITY_VIOLATION],handoff_module_ids=[ModuleId.POSITIONING,ModuleId.MENTOR])
    assert EvaluationBatch("bat_nested_order",(ordered,)).batch_fingerprint==EvaluationBatch("bat_nested_order",(reordered,)).batch_fingerprint

    side_a=ContradictionSide(claim_id="clm_a",object_key="object",segment_key="segment",period_key="period",metric_definition_key="metric")
    side_b=ContradictionSide(claim_id="clm_b",object_key="object",segment_key="segment",period_key="period",metric_definition_key="metric")
    contradictions=(ContradictionInput("ctr_a",side_a,side_b),ContradictionInput("ctr_b",side_a,side_b))
    assert EvaluationBatch("bat_ctr_order",(result_a,result_b),contradictions).batch_fingerprint==EvaluationBatch("bat_ctr_order",(result_b,result_a),tuple(reversed(contradictions))).batch_fingerprint

    ids_a=claim("clm_child",confidence=Confidence.LOW,lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=("clm_parent_a","clm_parent_b"),evidence_ids=("evd_a","evd_b"),assumption_ids=("asm_a","asm_b"),limitation_ids=("lim_a","lim_b"))
    ids_b=claim("clm_child",confidence=Confidence.LOW,lineage_type=ClaimLineageType.DERIVES,parent_claim_ids=("clm_parent_b","clm_parent_a"),evidence_ids=("evd_b","evd_a"),assumption_ids=("asm_b","asm_a"),limitation_ids=("lim_b","lim_a"))
    assert ids_a==ids_b
