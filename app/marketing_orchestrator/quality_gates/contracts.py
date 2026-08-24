from __future__ import annotations

from dataclasses import MISSING, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
import math
import re
from typing import Any
from contextvars import ContextVar

from app.module_registry import ModuleId, ModuleResultStatus
from .errors import QualityGateContractError

__all__ = (
    "ModuleId", "ModuleResultStatus", "ClaimType", "Confidence", "GateOutcome",
    "StructuralValidity", "ExecutionReadiness", "SynthesisEligibility",
    "EvidenceSufficiency", "EvidenceSourceClass", "ClaimLineageType", "Materiality",
    "AuthorityStatus", "LimitationReason", "FailureReason", "BlockingReason",
    "ContradictionState", "ContradictionPrecedenceReason", "FreshnessComparison",
    "ExclusionReason", "ExclusionSubjectType", "ReplanningDecision", "ReplanReason",
    "StopReason", "EvidenceRecord", "AssumptionRecord", "LimitationRecord",
    "NormalizedClaim", "NormalizedModuleResult", "ContradictionSide",
    "ContradictionInput", "EvaluationBatch", "GateDecision", "ContradictionRecord",
    "PropagatedClaimContext", "DerivedLimitationRecord", "ExclusionRecord", "SynthesisEligibilityManifest",
    "BatchEvaluationResult", "DecisionRequest", "DecisionResult",
)

class ClaimType(str, Enum):
    FACT="FACT"; OBSERVATION="OBSERVATION"; INFERENCE="INFERENCE"; HYPOTHESIS="HYPOTHESIS"; ASSUMPTION="ASSUMPTION"; FORECAST="FORECAST"; RECOMMENDATION="RECOMMENDATION"
class Confidence(str, Enum): UNKNOWN="UNKNOWN"; LOW="LOW"; MEDIUM="MEDIUM"; HIGH="HIGH"
class GateOutcome(str, Enum): PASS="PASS"; PASS_WITH_LIMITATIONS="PASS_WITH_LIMITATIONS"; FAIL="FAIL"; BLOCKED="BLOCKED"
class StructuralValidity(str, Enum): VALID="VALID"
class ExecutionReadiness(str, Enum): PLANNING_ONLY="PLANNING_ONLY"
class SynthesisEligibility(str, Enum): ELIGIBLE="ELIGIBLE"; INELIGIBLE="INELIGIBLE"
class EvidenceSufficiency(str, Enum): SUFFICIENT="SUFFICIENT"; LIMITED="LIMITED"; INSUFFICIENT="INSUFFICIENT"; NOT_ASSESSED="NOT_ASSESSED"
class EvidenceSourceClass(str, Enum): FIRST_PARTY="FIRST_PARTY"; EXTERNAL_PRIMARY="EXTERNAL_PRIMARY"; EXTERNAL_SECONDARY="EXTERNAL_SECONDARY"; GENERIC_BENCHMARK="GENERIC_BENCHMARK"; SYNTHETIC="SYNTHETIC"; UNKNOWN="UNKNOWN"
class ClaimLineageType(str, Enum): ORIGINAL="ORIGINAL"; REPEATS="REPEATS"; REFORMULATES="REFORMULATES"; DERIVES="DERIVES"
class Materiality(str, Enum): MATERIAL="MATERIAL"; NON_MATERIAL="NON_MATERIAL"
class AuthorityStatus(str, Enum): WITHIN_SCOPE="WITHIN_SCOPE"; REQUIRES_REVIEW="REQUIRES_REVIEW"; OUT_OF_SCOPE="OUT_OF_SCOPE"
class LimitationReason(str, Enum):
    MISSING_PREFERRED_INPUT="MISSING_PREFERRED_INPUT"; INCOMPLETE_COVERAGE="INCOMPLETE_COVERAGE"; INSUFFICIENT_EVIDENCE="INSUFFICIENT_EVIDENCE"; STALE_EVIDENCE="STALE_EVIDENCE"; TOOL_LIMIT="TOOL_LIMIT"; CAPABILITY_LIMIT="CAPABILITY_LIMIT"; ASSUMPTION_DEPENDENCY="ASSUMPTION_DEPENDENCY"; UNRESOLVED_CONTRADICTION="UNRESOLVED_CONTRADICTION"; OUT_OF_SCOPE="OUT_OF_SCOPE"
class FailureReason(str, Enum): MODULE_DECLARED_FAILURE="MODULE_DECLARED_FAILURE"; NO_USABLE_CLAIMS="NO_USABLE_CLAIMS"; INSUFFICIENT_EVIDENCE="INSUFFICIENT_EVIDENCE"; DECLARED_OUTPUT_MISSING="DECLARED_OUTPUT_MISSING"; AUTHORITY_VIOLATION="AUTHORITY_VIOLATION"
class BlockingReason(str, Enum): MISSING_BLOCKING_INPUT="MISSING_BLOCKING_INPUT"; MISSING_CAPABILITY="MISSING_CAPABILITY"; TOOL_UNAVAILABLE="TOOL_UNAVAILABLE"; DEPENDENCY_BLOCKED="DEPENDENCY_BLOCKED"; AUTHORIZATION_REQUIRED="AUTHORIZATION_REQUIRED"
class ContradictionState(str, Enum): UNRESOLVED="UNRESOLVED"; PRIORITIZED="PRIORITIZED"; INCOMPARABLE="INCOMPARABLE"
class ContradictionPrecedenceReason(str, Enum): FIRST_PARTY_NOT_OLDER_THAN_BENCHMARK="FIRST_PARTY_NOT_OLDER_THAN_BENCHMARK"
class FreshnessComparison(str, Enum): NEWER="NEWER"; OLDER="OLDER"; SAME="SAME"; UNKNOWN="UNKNOWN"
class ExclusionReason(str, Enum): RESULT_FAILED="RESULT_FAILED"; RESULT_BLOCKED="RESULT_BLOCKED"; UNRESOLVED_CONTRADICTION="UNRESOLVED_CONTRADICTION"; CONTRADICTION_PRECEDENCE="CONTRADICTION_PRECEDENCE"
class ExclusionSubjectType(str, Enum): RESULT="RESULT"; CLAIM="CLAIM"
class ReplanningDecision(str, Enum): CONTINUE_CURRENT_PLAN="CONTINUE_CURRENT_PLAN"; REPLAN_REQUIRED="REPLAN_REQUIRED"; STOP="STOP"; BLOCKED="BLOCKED"
class ReplanReason(str, Enum): MATERIAL_FINDING="MATERIAL_FINDING"; DEPENDENCY_INVALIDATED="DEPENDENCY_INVALIDATED"; REVERSIBLE_TEST_HIGHER_VALUE="REVERSIBLE_TEST_HIGHER_VALUE"
class StopReason(str, Enum): SCOPE_COMPLETE="SCOPE_COMPLETE"; SUFFICIENT_EVIDENCE="SUFFICIENT_EVIDENCE"; DIMINISHING_VALUE="DIMINISHING_VALUE"; TOOL_LIMIT_REACHED="TOOL_LIMIT_REACHED"; CAPABILITY_LIMIT_REACHED="CAPABILITY_LIMIT_REACHED"; RESULT_FAILED="RESULT_FAILED"

class _ContractMeta(type):
    """Validate dataclass argument binding without exposing generated TypeError."""
    def __call__(cls, *args, **kwargs):
        contract_fields=tuple(f for f in fields(cls) if f.init)
        positional=tuple(f for f in contract_fields if not f.kw_only)
        if len(args)>len(positional):
            raise QualityGateContractError(f"{cls.__name__} received too many positional arguments")
        supplied={f.name for f in positional[:len(args)]}
        unknown=tuple(sorted(k for k in kwargs if k not in {f.name for f in contract_fields}))
        if unknown:
            raise QualityGateContractError(f"{cls.__name__} received unknown field: {unknown[0]}")
        duplicate=tuple(f.name for f in positional[:len(args)] if f.name in kwargs)
        if duplicate:
            raise QualityGateContractError(f"{cls.__name__} received conflicting field: {duplicate[0]}")
        supplied.update(kwargs)
        missing=tuple(f.name for f in contract_fields if f.name not in supplied and f.default is MISSING and f.default_factory is MISSING)
        if missing:
            raise QualityGateContractError(f"{cls.__name__} missing required field: {missing[0]}")
        return super().__call__(*args, **kwargs)

class _Contract(metaclass=_ContractMeta):
    pass

_ID=re.compile(r"^(bat|res|clm|evd|asm|lim|ctr|exc)_[a-z0-9][a-z0-9_-]{0,62}$", re.ASCII)
_KEY=re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$", re.ASCII)
def _text(v: Any, field: str, *, prefix: str|None=None, key: bool=False) -> str:
    if type(v) is not str: raise QualityGateContractError(f"{field} must be an exact string")
    try: v.encode("utf-8")
    except UnicodeEncodeError as e: raise QualityGateContractError(f"{field} must contain valid Unicode scalar values") from e
    if prefix:
        if not _ID.fullmatch(v) or not v.startswith(prefix+"_"): raise QualityGateContractError(f"{field} must be a valid {prefix}_ ID")
    elif key:
        if not _KEY.fullmatch(v): raise QualityGateContractError(f"{field} must be a canonical comparison key")
    elif not v: raise QualityGateContractError(f"{field} must be non-empty")
    return v
def _enum(v: Any, cls: type[Enum], field: str):
    if type(v) is not cls: raise QualityGateContractError(f"{field} must be {cls.__name__}")
    return v
def _seq(v: Any, field: str, *, setlike=False, item_type=None):
    allowed=(list,tuple,set,frozenset) if setlike else (list,tuple)
    if type(v) not in allowed: raise QualityGateContractError(f"{field} must use an exact built-in container")
    x=tuple(v)
    if item_type is not None and any(type(item) is not item_type for item in x):raise QualityGateContractError(f"{field} contains an invalid item")
    if len(x)!=len(set(x)): raise QualityGateContractError(f"{field} contains duplicate values")
    return tuple(sorted(x, key=lambda z: z.value if isinstance(z,Enum) else z)) if setlike else tuple(x)
def _ids(v, field, prefix, *, setlike=False): return tuple(_text(x,field,prefix=prefix) for x in _seq(v,field,setlike=setlike,item_type=str))
def _dt(v, field):
    if v is None:return None
    if type(v) is not datetime: raise QualityGateContractError(f"{field} must be an exact aware datetime")
    try:
        if v.tzinfo is None or v.utcoffset() is None:raise ValueError("naive datetime")
        return v.astimezone(timezone.utc)
    except (TypeError,ValueError,OverflowError) as e: raise QualityGateContractError(f"{field} is invalid") from e
def _scalar(v,field):
    if type(v) not in (type(None),bool,int,float,str): raise QualityGateContractError(f"{field} must be an exact scalar")
    if type(v) is float and not math.isfinite(v): raise QualityGateContractError(f"{field} must be finite")
    if type(v) is str:
        try:v.encode("utf-8")
        except UnicodeEncodeError as e:raise QualityGateContractError(f"{field} must contain valid Unicode scalar values") from e
    return v

@dataclass(frozen=True,slots=True)
class EvidenceRecord(_Contract):
    evidence_id:str; source_class:EvidenceSourceClass; provenance:str; observed_at:datetime|None=None
    def __post_init__(self):
        object.__setattr__(self,"evidence_id",_text(self.evidence_id,"evidence_id",prefix="evd")); _enum(self.source_class,EvidenceSourceClass,"source_class"); _text(self.provenance,"provenance"); object.__setattr__(self,"observed_at",_dt(self.observed_at,"observed_at"))
@dataclass(frozen=True,slots=True)
class AssumptionRecord(_Contract):
    assumption_id:str; description:str; materiality:Materiality
    def __post_init__(self): _text(self.assumption_id,"assumption_id",prefix="asm"); _text(self.description,"description"); _enum(self.materiality,Materiality,"materiality")
@dataclass(frozen=True,slots=True)
class LimitationRecord(_Contract):
    limitation_id:str; reason:LimitationReason; materiality:Materiality; related_result_ids:tuple[str,...]=(); related_claim_ids:tuple[str,...]=(); related_contradiction_ids:tuple[str,...]=(); description:str|None=None
    def __post_init__(self):
        _text(self.limitation_id,"limitation_id",prefix="lim"); _enum(self.reason,LimitationReason,"reason"); _enum(self.materiality,Materiality,"materiality")
        for n,p in (("related_result_ids","res"),("related_claim_ids","clm"),("related_contradiction_ids","ctr")): object.__setattr__(self,n,tuple(sorted(_ids(getattr(self,n),n,p))))
        if not self.related_result_ids and not self.related_claim_ids: raise QualityGateContractError("caller limitation must reference a result or claim")
        if self.description is not None:_text(self.description,"description")
@dataclass(frozen=True,slots=True)
class NormalizedClaim(_Contract):
    claim_id:str; declared_output_name:str; claim_type:ClaimType; confidence:Confidence; authority_status:AuthorityStatus; value:Any; lineage_type:ClaimLineageType; parent_claim_ids:tuple[str,...]=(); evidence_ids:tuple[str,...]=(); assumption_ids:tuple[str,...]=(); limitation_ids:tuple[str,...]=()
    def __post_init__(self):
        _text(self.claim_id,"claim_id",prefix="clm"); _text(self.declared_output_name,"declared_output_name"); _enum(self.claim_type,ClaimType,"claim_type"); _enum(self.confidence,Confidence,"confidence"); _enum(self.authority_status,AuthorityStatus,"authority_status"); _scalar(self.value,"value"); _enum(self.lineage_type,ClaimLineageType,"lineage_type")
        for n,p in (("parent_claim_ids","clm"),("evidence_ids","evd"),("assumption_ids","asm"),("limitation_ids","lim")): object.__setattr__(self,n,tuple(sorted(_ids(getattr(self,n),n,p))))
        if (self.lineage_type is ClaimLineageType.ORIGINAL) != (not self.parent_claim_ids): raise QualityGateContractError("lineage_type and parent_claim_ids are incoherent")
@dataclass(frozen=True,slots=True,kw_only=True)
class NormalizedModuleResult(_Contract):
    result_id:str; module_id:ModuleId; module_status:ModuleResultStatus; claims:tuple[NormalizedClaim,...]=(); evidence:tuple[EvidenceRecord,...]=(); assumptions:tuple[AssumptionRecord,...]=(); limitations:tuple[LimitationRecord,...]=(); failure_reasons:frozenset[FailureReason]=frozenset(); blocking_reasons:frozenset[BlockingReason]=frozenset(); evidence_sufficiency:EvidenceSufficiency; handoff_module_ids:frozenset[ModuleId]=frozenset()
    def __post_init__(self):
        _text(self.result_id,"result_id",prefix="res"); _enum(self.module_id,ModuleId,"module_id"); _enum(self.module_status,ModuleResultStatus,"module_status"); _enum(self.evidence_sufficiency,EvidenceSufficiency,"evidence_sufficiency")
        for n,c in (("claims",NormalizedClaim),("evidence",EvidenceRecord),("assumptions",AssumptionRecord),("limitations",LimitationRecord)):
            vals=_seq(getattr(self,n),n,item_type=c)
            object.__setattr__(self,n,tuple(vals))
        for n,c in (("failure_reasons",FailureReason),("blocking_reasons",BlockingReason),("handoff_module_ids",ModuleId)):
            vals=_seq(getattr(self,n),n,setlike=True,item_type=c)
            object.__setattr__(self,n,frozenset(vals))
@dataclass(frozen=True,slots=True,kw_only=True)
class ContradictionSide(_Contract):
    claim_id:str; evidence_id:str|None=None; object_key:str; segment_key:str; period_key:str; metric_definition_key:str
    def __post_init__(self):
        _text(self.claim_id,"claim_id",prefix="clm")
        for n in ("object_key","segment_key","period_key","metric_definition_key"):_text(getattr(self,n),n,key=True)
        if self.evidence_id is not None:_text(self.evidence_id,"evidence_id",prefix="evd")
@dataclass(frozen=True,slots=True)
class ContradictionInput(_Contract):
    contradiction_id:str; left:ContradictionSide; right:ContradictionSide
    def __post_init__(self):
        _text(self.contradiction_id,"contradiction_id",prefix="ctr")
        if type(self.left) is not ContradictionSide or type(self.right) is not ContradictionSide:raise QualityGateContractError("left and right must be exact ContradictionSide values")
        if self.left.claim_id==self.right.claim_id:raise QualityGateContractError("contradiction side claim IDs must differ")
@dataclass(frozen=True,slots=True)
class EvaluationBatch(_Contract):
    batch_id:str; results:tuple[NormalizedModuleResult,...]; contradictions:tuple[ContradictionInput,...]=(); evaluation_at:datetime|None=None; batch_fingerprint:str=field(init=False)
    def __post_init__(self):
        _text(self.batch_id,"batch_id",prefix="bat")
        for n,c,nonempty in (("results",NormalizedModuleResult,True),("contradictions",ContradictionInput,False)):
            vals=_seq(getattr(self,n),n,item_type=c)
            if nonempty and not vals:raise QualityGateContractError("results must be non-empty")
            object.__setattr__(self,n,tuple(vals))
        object.__setattr__(self,"evaluation_at",_dt(self.evaluation_at,"evaluation_at"))
        from .canonical import fingerprint_batch
        object.__setattr__(self,"batch_fingerprint",fingerprint_batch(self))

_DERIVED_CONSTRUCTION:ContextVar[bool]=ContextVar("quality_gates_derived_construction",default=False)
class _Derived(_Contract):
    def __post_init__(self):
        if not _DERIVED_CONSTRUCTION.get(): raise QualityGateContractError("derived contracts are output-only")
    @classmethod
    def _make(cls,**kw):
        token=_DERIVED_CONSTRUCTION.set(True)
        try:return cls(**kw)
        finally:_DERIVED_CONSTRUCTION.reset(token)
@dataclass(frozen=True,slots=True)
class GateDecision(_Derived):
    batch_id:str; batch_fingerprint:str; result_id:str; module_id:ModuleId; module_status:ModuleResultStatus; structural_validity:StructuralValidity; gate_outcome:GateOutcome; evidence_sufficiency:EvidenceSufficiency; accepted_claim_ids:tuple[str,...]; excluded_claim_ids:tuple[str,...]; assumption_ids:tuple[str,...]; evidence_ids:tuple[str,...]; limitation_ids:tuple[str,...]; contradiction_ids:tuple[str,...]; failure_reasons:tuple[FailureReason,...]; blocking_reasons:tuple[BlockingReason,...]; authority_status:AuthorityStatus; synthesis_eligibility:SynthesisEligibility; execution_readiness:ExecutionReadiness
@dataclass(frozen=True,slots=True)
class PropagatedClaimContext(_Derived):
    batch_id:str; batch_fingerprint:str; claim_id:str; effective_confidence:Confidence; evidence_ids:tuple[str,...]=(); assumption_ids:tuple[str,...]=(); limitation_ids:tuple[str,...]=()
@dataclass(frozen=True,slots=True)
class ContradictionRecord(_Derived):
    batch_id:str; batch_fingerprint:str; contradiction_id:str; left:ContradictionSide; right:ContradictionSide; state:ContradictionState; preferred_claim_id:str|None; precedence_reason:ContradictionPrecedenceReason|None; preserved_claim_ids:tuple[str,...]; excluded_claim_ids:tuple[str,...]; derived_limitation_ids:tuple[str,...]
@dataclass(frozen=True,slots=True)
class DerivedLimitationRecord(_Derived):
    batch_id:str; batch_fingerprint:str; limitation_id:str; reason:LimitationReason; materiality:Materiality; related_result_ids:tuple[str,...]; related_claim_ids:tuple[str,...]; related_contradiction_ids:tuple[str,...]; description:None
@dataclass(frozen=True,slots=True)
class ExclusionRecord(_Derived):
    exclusion_id:str; batch_id:str; batch_fingerprint:str; subject_type:ExclusionSubjectType; result_id:str|None; claim_id:str|None; reason:ExclusionReason; contradiction_id:str|None; related_limitation_ids:tuple[str,...]
@dataclass(frozen=True,slots=True)
class SynthesisEligibilityManifest(_Derived):
    batch_id:str; batch_fingerprint:str; evaluated_result_ids:tuple[str,...]; accepted_result_ids:tuple[str,...]; accepted_claim_ids:tuple[str,...]; limitation_ids:tuple[str,...]; unresolved_contradiction_ids:tuple[str,...]; exclusions:tuple[ExclusionRecord,...]; execution_readiness:ExecutionReadiness
@dataclass(frozen=True,slots=True)
class BatchEvaluationResult(_Derived):
    batch_id:str; batch_fingerprint:str; gate_decisions:tuple[GateDecision,...]; propagated_claim_contexts:tuple[PropagatedClaimContext,...]; contradiction_records:tuple[ContradictionRecord,...]; derived_limitations:tuple[DerivedLimitationRecord,...]; exclusions:tuple[ExclusionRecord,...]; synthesis_manifest:SynthesisEligibilityManifest; execution_readiness:ExecutionReadiness
@dataclass(frozen=True,slots=True)
class DecisionRequest(_Contract):
    batch_id:str; batch_fingerprint:str; gate_decision:GateDecision; replan_reasons:frozenset[ReplanReason]=frozenset(); stop_reasons:frozenset[StopReason]=frozenset(); blocking_reasons:frozenset[BlockingReason]=frozenset()
    def __post_init__(self):
        _text(self.batch_id,"batch_id",prefix="bat")
        if type(self.batch_fingerprint) is not str or not re.fullmatch(r"[0-9a-f]{64}",self.batch_fingerprint):raise QualityGateContractError("batch_fingerprint must be lowercase SHA-256")
        if type(self.gate_decision) is not GateDecision:raise QualityGateContractError("gate_decision must be evaluator-produced")
        if (self.batch_id,self.batch_fingerprint)!=(self.gate_decision.batch_id,self.gate_decision.batch_fingerprint):raise QualityGateContractError("decision batch identity mismatch")
        for n,c in (("replan_reasons",ReplanReason),("stop_reasons",StopReason),("blocking_reasons",BlockingReason)):
            vals=_seq(getattr(self,n),n,setlike=True,item_type=c)
            object.__setattr__(self,n,frozenset(vals))
@dataclass(frozen=True,slots=True)
class DecisionResult(_Derived):
    batch_id:str; batch_fingerprint:str; result_id:str; gate_outcome:GateOutcome; decision:ReplanningDecision; replan_reasons:tuple[ReplanReason,...]; stop_reasons:tuple[StopReason,...]; blocking_reasons:tuple[BlockingReason,...]; execution_readiness:ExecutionReadiness
