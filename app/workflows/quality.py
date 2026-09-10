"""Explicit structured adapter to the existing metadata-only Quality Gates."""
from dataclasses import asdict
from datetime import datetime

from app.marketing_orchestrator import quality_gates as q
from app.module_registry import ModuleId, ModuleResultStatus

MODULES = {"analysis": ModuleId.COMPETITOR_ANALYSIS, "creative": ModuleId.CREATOR, "mentor": ModuleId.MENTOR}
CONFIDENCE = ["UNKNOWN", "LOW", "MEDIUM", "HIGH"]


def result_id(artifact):
    return f"res_{artifact['run_id']}_{artifact['step']}"


def normalized(artifact):
    rid = result_id(artifact)
    body = artifact["result"]
    assumptions = tuple(q.AssumptionRecord(f"asm_{artifact['run_id']}_{artifact['step']}_{i}", text, q.Materiality.MATERIAL)
                        for i, text in enumerate(body["assumptions"]))
    limitations = tuple(q.LimitationRecord(
        f"lim_{artifact['run_id']}_{artifact['step']}_{i}", q.LimitationReason.INCOMPLETE_COVERAGE,
        q.Materiality.MATERIAL, related_result_ids=(rid,), description=text,
    ) for i, text in enumerate(artifact["limitations"]))
    evidence = tuple(q.EvidenceRecord(e["id"], q.EvidenceSourceClass(e["source_class"]),
                                      e["provenance"], datetime.fromisoformat(e["observed_at"])) for e in artifact["evidence"])
    claims = tuple(q.NormalizedClaim(
        claim_id=cid, declared_output_name=claim["output_name"], claim_type=q.ClaimType(claim["kind"]),
        confidence=q.Confidence(claim["confidence"]), authority_status=q.AuthorityStatus.WITHIN_SCOPE,
        value=claim["text"], lineage_type=q.ClaimLineageType.DERIVES if claim["parent_claim_ids"] else q.ClaimLineageType.ORIGINAL,
        parent_claim_ids=tuple(claim["parent_claim_ids"]), evidence_ids=tuple(claim["evidence_ids"]),
        assumption_ids=tuple(a.assumption_id for a in assumptions), limitation_ids=tuple(l.limitation_id for l in limitations),
    ) for cid, claim in zip(artifact["claim_ids"], body["claims"]))
    return q.NormalizedModuleResult(
        result_id=rid, module_id=MODULES[artifact["step"]], module_status=ModuleResultStatus.PASS_WITH_LIMITATIONS,
        claims=claims, evidence=evidence, assumptions=assumptions, limitations=limitations,
        evidence_sufficiency=q.EvidenceSufficiency.LIMITED,
    )


def evaluate(artifact, upstream):
    results = [normalized(a) for step, a in upstream.items() if step in ("analysis", "creative")]
    results.append(normalized(artifact))
    batch = q.EvaluationBatch(batch_id=f"bat_{artifact['run_id']}_{artifact['step']}", results=tuple(results),
                              evaluation_at=datetime.fromisoformat(artifact["created_at"]))
    evaluation = q.QualityGateEvaluator().evaluate(batch)
    if result_id(artifact) not in evaluation.synthesis_manifest.accepted_result_ids:
        raise ValueError("Result is not eligible for presentation")
    return asdict(evaluation)
