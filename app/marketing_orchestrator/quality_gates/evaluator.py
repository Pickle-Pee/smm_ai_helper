from __future__ import annotations
import heapq
from app.module_registry import ModuleRegistry, ModuleRegistryError, ModuleRegistryNotFoundError, ModuleResultStatus
from .canonical import derive_id
from .contracts import *
from .errors import QualityGateContractError
from .propagation import confidence_within_parent_ceiling, compare_observed_at

def _unique(items,attr,label):
    seen={}
    for x in sorted(items,key=lambda y:getattr(y,attr)):
        k=getattr(x,attr)
        if k in seen:raise QualityGateContractError(f"duplicate {label} ID: {k}")
        seen[k]=x
    return seen
def _derived_id(prefix,components):return derive_id(prefix,components)[0]

class QualityGateEvaluator:
    def __init__(self,registry=None): self.registry=registry or ModuleRegistry.load()
    def evaluate(self,batch:EvaluationBatch)->BatchEvaluationResult:
        if type(batch) is not EvaluationBatch:raise QualityGateContractError("batch must be an exact EvaluationBatch")
        results=_unique(batch.results,"result_id","result")
        claims=_unique([c for r in batch.results for c in r.claims],"claim_id","claim")
        evidence=_unique([e for r in batch.results for e in r.evidence],"evidence_id","evidence")
        assumptions=_unique([a for r in batch.results for a in r.assumptions],"assumption_id","assumption")
        limitations=_unique([l for r in batch.results for l in r.limitations],"limitation_id","limitation")
        contradictions=_unique(batch.contradictions,"contradiction_id","contradiction")
        owner={c.claim_id:r for r in batch.results for c in r.claims}
        ev_owner={e.evidence_id:r for r in batch.results for e in r.evidence}
        try:
            if self.registry.version!="1.0.0" or len(self.registry.descriptors)!=15 or any(d.execution_binding is not None for d in self.registry.descriptors):raise QualityGateContractError("Registry must be metadata-only version 1.0.0 with fifteen descriptors")
            for r in sorted(batch.results,key=lambda x:x.result_id):
                descriptor=self.registry.get(r.module_id)
                for c in sorted(r.claims,key=lambda x:x.claim_id):
                    if c.declared_output_name not in descriptor.outputs:raise QualityGateContractError(f"declared_output_name is not registered for result {r.result_id}")
                    for pid in c.parent_claim_ids:
                        if pid not in claims:raise QualityGateContractError(f"unresolved parent claim ID: {pid}")
                    for eid in c.evidence_ids:
                        if eid not in evidence or ev_owner[eid] is not r:raise QualityGateContractError(f"unresolved local evidence ID: {eid}")
                    local_a={x.assumption_id for x in r.assumptions}; local_l={x.limitation_id for x in r.limitations}
                    if any(x not in local_a for x in c.assumption_ids):raise QualityGateContractError(f"unresolved local assumption reference in claim {c.claim_id}")
                    if any(x not in local_l for x in c.limitation_ids):raise QualityGateContractError(f"unresolved local limitation reference in claim {c.claim_id}")
                for l in r.limitations:
                    if any(x not in results for x in l.related_result_ids) or any(x not in claims for x in l.related_claim_ids) or any(x not in contradictions for x in l.related_contradiction_ids):raise QualityGateContractError(f"unresolved limitation reference: {l.limitation_id}")
                for h in r.handoff_module_ids:
                    self.registry.get(h)
                    if h not in descriptor.handoffs:raise QualityGateContractError(f"handoff is not registered for result {r.result_id}")
        except (ModuleRegistryError,ModuleRegistryNotFoundError,KeyError,ValueError,TypeError,OverflowError) as e:
            if isinstance(e,QualityGateContractError):raise
            raise QualityGateContractError("Registry validation failed") from e
        contexts_by_id={}
        children={claim_id:[] for claim_id in claims}
        indegree={claim_id:len(claim.parent_claim_ids) for claim_id,claim in claims.items()}
        for claim_id,claim in claims.items():
            for parent_id in claim.parent_claim_ids:children[parent_id].append(claim_id)
        for child_ids in children.values():child_ids.sort()
        ready=[claim_id for claim_id,count in indegree.items() if count==0]
        heapq.heapify(ready)
        while ready:
            claim_id=heapq.heappop(ready)
            claim=claims[claim_id]
            parents=tuple(contexts_by_id[parent_id] for parent_id in claim.parent_claim_ids)
            if not confidence_within_parent_ceiling(claim.confidence,[p.effective_confidence for p in parents]):
                raise QualityGateContractError(f"claim confidence exceeds parent ceiling: {claim.claim_id}")
            contexts_by_id[claim_id]=PropagatedClaimContext._make(
                batch_id=batch.batch_id,batch_fingerprint=batch.batch_fingerprint,claim_id=claim.claim_id,
                effective_confidence=claim.confidence,
                evidence_ids=tuple(sorted({*claim.evidence_ids,*(x for p in parents for x in p.evidence_ids)})),
                assumption_ids=tuple(sorted({*claim.assumption_ids,*(x for p in parents for x in p.assumption_ids)})),
                limitation_ids=tuple(sorted({*claim.limitation_ids,*(x for p in parents for x in p.limitation_ids)})),
            )
            for child_id in children[claim_id]:
                indegree[child_id]-=1
                if indegree[child_id]==0:heapq.heappush(ready,child_id)
        if len(contexts_by_id)!=len(claims):raise QualityGateContractError("lineage cycle detected")
        propagated_contexts=tuple(contexts_by_id[x] for x in sorted(contexts_by_id))
        base={r.result_id:self._base(r) for r in batch.results}
        records=[]; dlimits={}; exclusions={}; collision={}
        def add_exclusion(rid,cid,reason,ctr=None,lim=None):
            st=ExclusionSubjectType.CLAIM if cid else ExclusionSubjectType.RESULT
            comps=("quality-gates-v1","exclusion",batch.batch_fingerprint,st.value,rid or "",cid or "",reason.value,ctr or "")
            eid,pre=derive_id("exc",comps)
            if eid in collision and collision[eid]!=pre:raise QualityGateContractError("derived exclusion ID collision")
            collision[eid]=pre
            exclusions[(eid,pre)]=ExclusionRecord._make(batch_id=batch.batch_id,batch_fingerprint=batch.batch_fingerprint,exclusion_id=eid,subject_type=st,result_id=rid if not cid else None,claim_id=cid,reason=reason,contradiction_id=ctr,related_limitation_ids=(lim,) if lim else ())
        for c in sorted(batch.contradictions,key=lambda x:x.contradiction_id):
            left,right=c.left,c.right
            if left.claim_id not in claims or right.claim_id not in claims:raise QualityGateContractError(f"unresolved contradiction claim reference: {c.contradiction_id}")
            if (left.evidence_id is None)!=(right.evidence_id is None):raise QualityGateContractError("selected contradiction evidence must be paired")
            if left.evidence_id is not None:
                for side in (left,right):
                    if side.evidence_id not in evidence or side.evidence_id not in claims[side.claim_id].evidence_ids:raise QualityGateContractError(f"selected evidence is not attached to claim {side.claim_id}")
            state=ContradictionState.UNRESOLVED; preferred=None; reason=None
            if any(getattr(left,n)!=getattr(right,n) for n in ("object_key","segment_key","period_key","metric_definition_key")):
                state=ContradictionState.INCOMPARABLE
            elif left.evidence_id is not None:
                if left.evidence_id!=right.evidence_id:
                    le,re=evidence[left.evidence_id],evidence[right.evidence_id]
                    pairs=((le,re,left.claim_id),(re,le,right.claim_id))
                    for first,bench,cid in pairs:
                        if first.source_class is EvidenceSourceClass.FIRST_PARTY and bench.source_class is EvidenceSourceClass.GENERIC_BENCHMARK and compare_observed_at(first.observed_at,bench.observed_at) in (FreshnessComparison.NEWER,FreshnessComparison.SAME):state=ContradictionState.PRIORITIZED;preferred=cid;reason=ContradictionPrecedenceReason.FIRST_PARTY_NOT_OLDER_THAN_BENCHMARK
            excluded=[]; dlids=[]
            if state is ContradictionState.PRIORITIZED:
                loser=right.claim_id if preferred==left.claim_id else left.claim_id; excluded=[loser]; add_exclusion(None,loser,ExclusionReason.CONTRADICTION_PRECEDENCE,c.contradiction_id)
            else:
                excluded=sorted({left.claim_id,right.claim_id})
                for rid in sorted({owner[x].result_id for x in excluded}):
                    affected=tuple(sorted(x for x in excluded if owner[x].result_id==rid))
                    comps=("quality-gates-v1","limitation",batch.batch_fingerprint,rid,c.contradiction_id,LimitationReason.UNRESOLVED_CONTRADICTION.value)
                    lid,pre=derive_id("lim",comps)
                    if lid in collision and collision[lid]!=pre:raise QualityGateContractError("derived limitation ID collision")
                    collision[lid]=pre
                    dlimits[(lid,pre)]=DerivedLimitationRecord._make(batch_id=batch.batch_id,batch_fingerprint=batch.batch_fingerprint,limitation_id=lid,reason=LimitationReason.UNRESOLVED_CONTRADICTION,materiality=Materiality.MATERIAL,related_result_ids=(rid,),related_claim_ids=affected,related_contradiction_ids=(c.contradiction_id,),description=None);dlids.append(lid)
                    for cid in affected:add_exclusion(None,cid,ExclusionReason.UNRESOLVED_CONTRADICTION,c.contradiction_id,lid)
            records.append(ContradictionRecord._make(batch_id=batch.batch_id,batch_fingerprint=batch.batch_fingerprint,contradiction_id=c.contradiction_id,left=left,right=right,state=state,preserved_claim_ids=tuple(sorted({left.claim_id,right.claim_id})),excluded_claim_ids=tuple(excluded),preferred_claim_id=preferred,precedence_reason=reason,derived_limitation_ids=tuple(sorted(dlids))))
        claim_exc={x.claim_id for x in exclusions.values() if x.claim_id}
        decisions=[]
        for r in sorted(batch.results,key=lambda x:x.result_id):
            accepted=tuple(sorted(c.claim_id for c in r.claims if c.claim_id not in claim_exc)); excluded=tuple(sorted(c.claim_id for c in r.claims if c.claim_id in claim_exc)); outcome=base[r.result_id]
            fr=set(r.failure_reasons)
            related_dl=tuple(sorted(x.limitation_id for x in dlimits.values() if r.result_id in x.related_result_ids))
            owned_contexts=tuple(contexts_by_id[c.claim_id] for c in r.claims)
            propagated_evidence={x for c in owned_contexts for x in c.evidence_ids}
            propagated_assumptions={x for c in owned_contexts for x in c.assumption_ids}
            propagated_limitations={x for c in owned_contexts for x in c.limitation_ids}
            inherited_material=any(limitations[x].materiality is Materiality.MATERIAL for x in propagated_limitations)
            if outcome in (GateOutcome.PASS,GateOutcome.PASS_WITH_LIMITATIONS) and not accepted:outcome=GateOutcome.FAIL;fr.add(FailureReason.NO_USABLE_CLAIMS)
            elif related_dl or inherited_material:outcome=GateOutcome.PASS_WITH_LIMITATIONS
            if outcome in (GateOutcome.FAIL,GateOutcome.BLOCKED):add_exclusion(r.result_id,None,ExclusionReason.RESULT_FAILED if outcome is GateOutcome.FAIL else ExclusionReason.RESULT_BLOCKED)
            auth=AuthorityStatus.REQUIRES_REVIEW if any(c.authority_status is AuthorityStatus.REQUIRES_REVIEW for c in r.claims if c.claim_id in accepted) else AuthorityStatus.WITHIN_SCOPE
            decisions.append(GateDecision._make(batch_id=batch.batch_id,batch_fingerprint=batch.batch_fingerprint,result_id=r.result_id,module_id=r.module_id,module_status=r.module_status,structural_validity=StructuralValidity.VALID,gate_outcome=outcome,synthesis_eligibility=SynthesisEligibility.ELIGIBLE if outcome in (GateOutcome.PASS,GateOutcome.PASS_WITH_LIMITATIONS) else SynthesisEligibility.INELIGIBLE,execution_readiness=ExecutionReadiness.PLANNING_ONLY,authority_status=auth,evidence_sufficiency=r.evidence_sufficiency,accepted_claim_ids=accepted,excluded_claim_ids=excluded,evidence_ids=tuple(sorted({*(x.evidence_id for x in r.evidence),*propagated_evidence})),assumption_ids=tuple(sorted({*(x.assumption_id for x in r.assumptions),*propagated_assumptions})),limitation_ids=tuple(sorted({*(x.limitation_id for x in r.limitations),*propagated_limitations,*related_dl})),contradiction_ids=tuple(sorted(c.contradiction_id for c in batch.contradictions if c.left.claim_id in {x.claim_id for x in r.claims} or c.right.claim_id in {x.claim_id for x in r.claims})),failure_reasons=tuple(sorted(fr,key=lambda x:x.value)),blocking_reasons=tuple(sorted(r.blocking_reasons,key=lambda x:x.value))))
        accepted_results={d.result_id for d in decisions if d.gate_outcome in (GateOutcome.PASS,GateOutcome.PASS_WITH_LIMITATIONS)}
        all_exc=tuple(sorted(exclusions.values(),key=lambda x:x.exclusion_id)); manifest_exc=tuple(x for x in all_exc if (x.result_id is not None) or owner[x.claim_id].result_id in accepted_results)
        manifest=SynthesisEligibilityManifest._make(batch_id=batch.batch_id,batch_fingerprint=batch.batch_fingerprint,evaluated_result_ids=tuple(sorted(results)),accepted_result_ids=tuple(sorted(accepted_results)),accepted_claim_ids=tuple(sorted(x for d in decisions if d.result_id in accepted_results for x in d.accepted_claim_ids)),limitation_ids=tuple(sorted({x for d in decisions if d.result_id in accepted_results for x in d.limitation_ids})),unresolved_contradiction_ids=tuple(sorted(r.contradiction_id for r in records if r.state is not ContradictionState.PRIORITIZED and any(owner[x].result_id in accepted_results for x in r.preserved_claim_ids))),exclusions=manifest_exc,execution_readiness=ExecutionReadiness.PLANNING_ONLY)
        return BatchEvaluationResult._make(batch_id=batch.batch_id,batch_fingerprint=batch.batch_fingerprint,gate_decisions=tuple(decisions),propagated_claim_contexts=propagated_contexts,contradiction_records=tuple(records),derived_limitations=tuple(sorted(dlimits.values(),key=lambda x:x.limitation_id)),exclusions=all_exc,synthesis_manifest=manifest,execution_readiness=ExecutionReadiness.PLANNING_ONLY)
    @staticmethod
    def _base(r):
        material=any(x.materiality is Materiality.MATERIAL for x in r.limitations)
        if r.failure_reasons and r.blocking_reasons:raise QualityGateContractError("failure and blocking reasons are mutually exclusive")
        if r.module_status in (ModuleResultStatus.PASS,ModuleResultStatus.PASS_WITH_LIMITATIONS) and any(c.authority_status is AuthorityStatus.OUT_OF_SCOPE for c in r.claims):raise QualityGateContractError("accepted result contains OUT_OF_SCOPE claim")
        if r.module_status is ModuleResultStatus.PASS:
            if not r.claims or r.evidence_sufficiency is not EvidenceSufficiency.SUFFICIENT or material or r.failure_reasons or r.blocking_reasons:raise QualityGateContractError("invalid PASS state")
            return GateOutcome.PASS
        if r.module_status is ModuleResultStatus.PASS_WITH_LIMITATIONS:
            if not r.claims or r.evidence_sufficiency not in (EvidenceSufficiency.SUFFICIENT,EvidenceSufficiency.LIMITED) or not material or r.failure_reasons or r.blocking_reasons:raise QualityGateContractError("invalid PASS_WITH_LIMITATIONS state")
            return GateOutcome.PASS_WITH_LIMITATIONS
        if r.module_status is ModuleResultStatus.FAIL:
            if r.claims or r.evidence_sufficiency not in (EvidenceSufficiency.INSUFFICIENT,EvidenceSufficiency.NOT_ASSESSED) or not r.failure_reasons or r.blocking_reasons:raise QualityGateContractError("invalid FAIL state")
            return GateOutcome.FAIL
        if r.module_status is ModuleResultStatus.BLOCKED:
            if r.claims or r.evidence_sufficiency is not EvidenceSufficiency.NOT_ASSESSED or r.failure_reasons or not r.blocking_reasons:raise QualityGateContractError("invalid BLOCKED state")
            return GateOutcome.BLOCKED
        raise QualityGateContractError("invalid module status")
