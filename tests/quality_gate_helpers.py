from datetime import datetime,timezone
from app.module_registry import ModuleId,ModuleResultStatus
from app.marketing_orchestrator.quality_gates import *

def claim(cid="clm_one",**kw):
    return NormalizedClaim(claim_id=cid,declared_output_name=kw.pop("declared_output_name","strategic_diagnosis"),claim_type=kw.pop("claim_type",ClaimType.FACT),confidence=kw.pop("confidence",Confidence.HIGH),authority_status=kw.pop("authority_status",AuthorityStatus.WITHIN_SCOPE),value=kw.pop("value","value"),lineage_type=kw.pop("lineage_type",ClaimLineageType.ORIGINAL),**kw)
def result(rid="res_one",claims=None,**kw):
    return NormalizedModuleResult(result_id=rid,module_id=kw.pop("module_id",ModuleId.VIRTUAL_CMO),module_status=kw.pop("module_status",ModuleResultStatus.PASS),claims=(claim(),) if claims is None else claims,evidence_sufficiency=kw.pop("evidence_sufficiency",EvidenceSufficiency.SUFFICIENT),**kw)
def batch(results=None,**kw):return EvaluationBatch(batch_id="bat_one",results=(result(),) if results is None else results,**kw)
UTC=datetime(2025,1,1,tzinfo=timezone.utc)
