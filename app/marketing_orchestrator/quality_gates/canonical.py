from __future__ import annotations
from datetime import datetime
from enum import Enum
import hashlib, struct
from typing import Any

def _node(v:Any):
    if v is None:return {"t":"null"}
    if type(v) is bool:return {"t":"bool","v":v}
    if type(v) is str:return {"t":"str","v":v}
    if type(v) is int:return {"t":"int","v":str(v)}
    if type(v) is float:return {"t":"float64","v":struct.pack(">d",v).hex()}
    if isinstance(v,Enum):return {"t":"enum","n":type(v).__name__,"v":v.value}
    if type(v) is datetime:return {"t":"datetime","v":v.strftime("%Y-%m-%dT%H:%M:%S.%fZ")}
    if type(v) in (tuple,list):return {"t":"array","v":[x if type(x) is dict else _node(x) for x in v]}
    if type(v) is dict:return v
    raise TypeError("unsupported internal canonical value")

def _quote(s:str)->str:
    out='"'
    escapes={8:"\\b",9:"\\t",10:"\\n",12:"\\f",13:"\\r"}
    for ch in s:
        n=ord(ch)
        if ch=='"':out+='\\"'
        elif ch=='\\':out+='\\\\'
        elif n in escapes:out+=escapes[n]
        elif n<32:out+=f"\\u{n:04x}"
        else:out+=ch
    return out+'"'
def rfc8785_dumps(v:Any)->str:
    if v is None:return "null"
    if type(v) is bool:return "true" if v else "false"
    if type(v) is int:return str(v)
    if type(v) is str:return _quote(v)
    if type(v) is list:return "["+",".join(rfc8785_dumps(x) for x in v)+"]"
    if type(v) is dict:
        keys=sorted(v,key=lambda x:x.encode("utf-16be"))
        return "{"+",".join(_quote(k)+":"+rfc8785_dumps(v[k]) for k in keys)+"}"
    raise TypeError("canonical tree contains unsupported value")
def _record(d):return {k:_node(v) for k,v in d.items()}
def fingerprint_batch(batch)->str:
    results=[]
    for r in sorted(batch.results,key=lambda x:x.result_id):
        claims=[_record({"claim_id":c.claim_id,"declared_output_name":c.declared_output_name,"claim_type":c.claim_type,"confidence":c.confidence,"authority_status":c.authority_status,"value":c.value,"lineage_type":c.lineage_type,"parent_claim_ids":tuple(sorted(c.parent_claim_ids)),"evidence_ids":tuple(sorted(c.evidence_ids)),"assumption_ids":tuple(sorted(c.assumption_ids)),"limitation_ids":tuple(sorted(c.limitation_ids))}) for c in sorted(r.claims,key=lambda x:x.claim_id)]
        evidence=[_record({"evidence_id":e.evidence_id,"source_class":e.source_class,"provenance":e.provenance,"observed_at":e.observed_at}) for e in sorted(r.evidence,key=lambda x:x.evidence_id)]
        assumptions=[_record({"assumption_id":a.assumption_id,"description":a.description,"materiality":a.materiality}) for a in sorted(r.assumptions,key=lambda x:x.assumption_id)]
        limits=[_record({"limitation_id":l.limitation_id,"reason":l.reason,"materiality":l.materiality,"related_result_ids":tuple(sorted(l.related_result_ids)),"related_claim_ids":tuple(sorted(l.related_claim_ids)),"related_contradiction_ids":tuple(sorted(l.related_contradiction_ids)),"description":l.description}) for l in sorted(r.limitations,key=lambda x:x.limitation_id)]
        results.append(_record({"result_id":r.result_id,"module_id":r.module_id,"module_status":r.module_status,"claims":claims,"evidence":evidence,"assumptions":assumptions,"limitations":limits,"failure_reasons":tuple(sorted(r.failure_reasons,key=lambda x:x.value)),"blocking_reasons":tuple(sorted(r.blocking_reasons,key=lambda x:x.value)),"evidence_sufficiency":r.evidence_sufficiency,"handoff_module_ids":tuple(sorted(r.handoff_module_ids,key=lambda x:x.value))}))
    def side(s):return _record({"claim_id":s.claim_id,"evidence_id":s.evidence_id,"object_key":s.object_key,"segment_key":s.segment_key,"period_key":s.period_key,"metric_definition_key":s.metric_definition_key})
    contradictions=[_record({"contradiction_id":c.contradiction_id,"left":side(c.left),"right":side(c.right)}) for c in sorted(batch.contradictions,key=lambda x:x.contradiction_id)]
    tree={"schema":"quality-gates-batch-v1","batch_id":batch.batch_id,"evaluation_at":_node(batch.evaluation_at),"results":results,"contradictions":contradictions}
    return hashlib.sha256(rfc8785_dumps(tree).encode()).hexdigest()

def derive_id(prefix:str, components:tuple[str,...], *, digest=hashlib.sha256)->tuple[str,bytes]:
    raw=b"".join(str(len(x.encode())).encode()+b":"+x.encode() for x in components)
    return prefix+"_"+digest(raw).hexdigest()[:32],raw
