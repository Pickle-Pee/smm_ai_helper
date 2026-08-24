from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import timedelta
from enum import Enum
from typing import Callable

import pytest

from app.marketing_orchestrator.quality_gates import *
from app.module_registry import ModuleId, ModuleResultStatus
from tests.quality_gate_helpers import UTC, batch, claim, result


BatchFactory = Callable[[], EvaluationBatch]


@dataclass(frozen=True)
class FingerprintCase:
    case_id: str
    source: str
    baseline: BatchFactory
    mutated: BatchFactory
    equal: bool = False
    category: str = "leaf"
    changed_paths: frozenset[str] = frozenset()
    element_count: int = 0


def _pass(rid="res_one", cid="clm_one", **kwargs):
    return result(rid, claims=(claim(cid),), **kwargs)


def _limited(rid="res_one", cid="clm_one", *, limitation_id="lim_one", **kwargs):
    limitation = LimitationRecord(
        limitation_id,
        LimitationReason.TOOL_LIMIT,
        Materiality.MATERIAL,
        (rid,),
        (cid,),
    )
    return result(
        rid,
        claims=(claim(cid, limitation_ids=(limitation_id,)),),
        limitations=(limitation,),
        module_status=ModuleResultStatus.PASS_WITH_LIMITATIONS,
        evidence_sufficiency=EvidenceSufficiency.LIMITED,
        **kwargs,
    )


def _fail(*, reasons=(FailureReason.MODULE_DECLARED_FAILURE,), module_id=ModuleId.VIRTUAL_CMO):
    return result(
        claims=(), module_id=module_id, module_status=ModuleResultStatus.FAIL,
        evidence_sufficiency=EvidenceSufficiency.INSUFFICIENT,
        failure_reasons=reasons,
    )


def _blocked(*, reasons=(BlockingReason.MISSING_BLOCKING_INPUT,)):
    return result(
        claims=(), module_status=ModuleResultStatus.BLOCKED,
        evidence_sufficiency=EvidenceSufficiency.NOT_ASSESSED,
        blocking_reasons=reasons,
    )


def _side(cid, eid=None, *, object_key="object", segment_key="segment", period_key="period", metric_definition_key="metric"):
    return ContradictionSide(
        claim_id=cid, evidence_id=eid, object_key=object_key, segment_key=segment_key,
        period_key=period_key, metric_definition_key=metric_definition_key,
    )


def _contradiction_batch(*, left=None, right=None, contradiction_id="ctr_one", extra_claim=True):
    evidence = (
        EvidenceRecord("evd_left", EvidenceSourceClass.FIRST_PARTY, "left", UTC),
        EvidenceRecord("evd_left_alt", EvidenceSourceClass.EXTERNAL_PRIMARY, "left-alt", UTC),
        EvidenceRecord("evd_right", EvidenceSourceClass.GENERIC_BENCHMARK, "right", UTC),
        EvidenceRecord("evd_right_alt", EvidenceSourceClass.EXTERNAL_SECONDARY, "right-alt", UTC),
    )
    claims = (
        claim("clm_left", evidence_ids=("evd_left", "evd_left_alt")),
        claim("clm_right", evidence_ids=("evd_right", "evd_right_alt")),
        *((claim("clm_spare"),) if extra_claim else ()),
    )
    module_result = result("res_one", claims=claims, evidence=evidence)
    contradiction = ContradictionInput(
        contradiction_id,
        left or _side("clm_left", "evd_left"),
        right or _side("clm_right", "evd_right"),
    )
    return EvaluationBatch("bat_contradiction", (module_result,), (contradiction,), UTC)


def _lineage_batch(*, lineage_type=ClaimLineageType.DERIVES, parents=("clm_parent_a",)):
    claims = (
        claim("clm_parent_a", confidence=Confidence.MEDIUM),
        claim("clm_parent_b", confidence=Confidence.MEDIUM),
        claim("clm_child", confidence=Confidence.LOW, lineage_type=lineage_type, parent_claim_ids=parents),
    )
    return EvaluationBatch("bat_lineage_fp", (result(claims=claims),))


def _records_batch(**overrides):
    evidence = overrides.pop("evidence", (EvidenceRecord("evd_a", EvidenceSourceClass.FIRST_PARTY, "a", UTC),))
    assumptions = overrides.pop("assumptions", (AssumptionRecord("asm_a", "a", Materiality.MATERIAL),))
    limitations = overrides.pop("limitations", (LimitationRecord("lim_a", LimitationReason.TOOL_LIMIT, Materiality.NON_MATERIAL, ("res_one",), ("clm_one",)),))
    current_claim = overrides.pop("current_claim", claim("clm_one", evidence_ids=("evd_a",), assumption_ids=("asm_a",), limitation_ids=("lim_a",)))
    return EvaluationBatch("bat_records", (result(claims=(current_claim,), evidence=evidence, assumptions=assumptions, limitations=limitations, **overrides),))


def _related_batch(*, result_ref=("res_a",), claim_ref=("clm_a",), contradiction_ref=()):
    side_a, side_b = _side("clm_a"), _side("clm_b")
    contradictions = (
        ContradictionInput("ctr_a", side_a, side_b),
        ContradictionInput("ctr_b", side_a, side_b),
    )
    limitation = LimitationRecord(
        "lim_a", LimitationReason.TOOL_LIMIT, Materiality.NON_MATERIAL,
        result_ref, claim_ref, contradiction_ref,
    )
    first = result("res_a", claims=(claim("clm_a", limitation_ids=("lim_a",)), claim("clm_b")), limitations=(limitation,))
    second = _pass("res_b", "clm_c")
    return EvaluationBatch("bat_related", (first, second), contradictions)


def _replace_first_result(source, **changes):
    return replace(source, results=(replace(source.results[0], **changes), *source.results[1:]))


def _replace_first_claim(source, **changes):
    current = source.results[0]
    return _replace_first_result(source, claims=(replace(current.claims[0], **changes), *current.claims[1:]))


def _replace_first_record(source, collection, **changes):
    current = source.results[0]
    values = getattr(current, collection)
    return _replace_first_result(source, **{collection: (replace(values[0], **changes), *values[1:])})


def _replace_side(source, side_name, **changes):
    contradiction = source.contradictions[0]
    side = replace(getattr(contradiction, side_name), **changes)
    return replace(source, contradictions=(replace(contradiction, **{side_name: side}), *source.contradictions[1:]))


def _leaf(case_id, source, baseline, mutate):
    return FingerprintCase(case_id, source, baseline, lambda: mutate(baseline()))


LEAF_CASES = (
    _leaf("evaluation-at", "batch.evaluation_at", lambda: batch(evaluation_at=UTC), lambda b: replace(b, evaluation_at=UTC + timedelta(seconds=1))),
    _leaf("module-id", "result.module_id", lambda: batch(results=(_fail(),)), lambda b: _replace_first_result(b, module_id=ModuleId.MENTOR)),
    _leaf("failure-reasons", "result.failure_reasons", lambda: batch(results=(_fail(),)), lambda b: _replace_first_result(b, failure_reasons={FailureReason.AUTHORITY_VIOLATION})),
    _leaf("blocking-reasons", "result.blocking_reasons", lambda: batch(results=(_blocked(),)), lambda b: _replace_first_result(b, blocking_reasons={BlockingReason.MISSING_CAPABILITY})),
    _leaf("evidence-sufficiency", "result.evidence_sufficiency", lambda: batch(results=(_limited(),)), lambda b: _replace_first_result(b, evidence_sufficiency=EvidenceSufficiency.SUFFICIENT)),
    _leaf("handoff-membership", "result.handoff_module_ids", lambda: batch(results=(_pass(handoff_module_ids={ModuleId.POSITIONING}),)), lambda b: _replace_first_result(b, handoff_module_ids={ModuleId.EXPERIMENTS})),
    _leaf("declared-output", "claim.declared_output_name", lambda: batch(), lambda b: _replace_first_claim(b, declared_output_name="main_growth_constraint")),
    _leaf("claim-type", "claim.claim_type", lambda: batch(), lambda b: _replace_first_claim(b, claim_type=ClaimType.INFERENCE)),
    _leaf("confidence", "claim.confidence", lambda: batch(), lambda b: _replace_first_claim(b, confidence=Confidence.MEDIUM)),
    _leaf("authority", "claim.authority_status", lambda: batch(), lambda b: _replace_first_claim(b, authority_status=AuthorityStatus.REQUIRES_REVIEW)),
    _leaf("claim-value", "claim.value", lambda: batch(), lambda b: _replace_first_claim(b, value="changed")),
    _leaf("lineage-type", "claim.lineage_type", lambda: _lineage_batch(), lambda b: _replace_first_result(b, claims=(*b.results[0].claims[:2], replace(b.results[0].claims[2], lineage_type=ClaimLineageType.REFORMULATES)))),
    _leaf("parent-ids", "claim.parent_claim_ids", lambda: _lineage_batch(), lambda b: _replace_first_result(b, claims=(*b.results[0].claims[:2], replace(b.results[0].claims[2], parent_claim_ids=("clm_parent_b",))))),
    _leaf("claim-evidence-ids", "claim.evidence_ids", _records_batch, lambda b: _replace_first_claim(b, evidence_ids=())),
    _leaf("claim-assumption-ids", "claim.assumption_ids", _records_batch, lambda b: _replace_first_claim(b, assumption_ids=())),
    _leaf("claim-limitation-ids", "claim.limitation_ids", _records_batch, lambda b: _replace_first_claim(b, limitation_ids=())),
    _leaf("evidence-source", "evidence.source_class", _records_batch, lambda b: _replace_first_record(b, "evidence", source_class=EvidenceSourceClass.UNKNOWN)),
    _leaf("evidence-provenance", "evidence.provenance", _records_batch, lambda b: _replace_first_record(b, "evidence", provenance="changed")),
    _leaf("evidence-observed-at", "evidence.observed_at", _records_batch, lambda b: _replace_first_record(b, "evidence", observed_at=UTC + timedelta(seconds=1))),
    _leaf("assumption-description", "assumption.description", _records_batch, lambda b: _replace_first_record(b, "assumptions", description="changed")),
    _leaf("assumption-materiality", "assumption.materiality", _records_batch, lambda b: _replace_first_record(b, "assumptions", materiality=Materiality.NON_MATERIAL)),
    _leaf("limitation-reason", "limitation.reason", _records_batch, lambda b: _replace_first_record(b, "limitations", reason=LimitationReason.CAPABILITY_LIMIT)),
    _leaf("limitation-result-refs", "limitation.related_result_ids", _related_batch, lambda b: _replace_first_record(b, "limitations", related_result_ids=("res_b",))),
    _leaf("limitation-claim-refs", "limitation.related_claim_ids", _related_batch, lambda b: _replace_first_record(b, "limitations", related_claim_ids=("clm_b",))),
    _leaf("limitation-contradiction-refs", "limitation.related_contradiction_ids", lambda: _related_batch(contradiction_ref=("ctr_a",)), lambda b: _replace_first_record(b, "limitations", related_contradiction_ids=("ctr_b",))),
    _leaf("limitation-description", "limitation.description", _records_batch, lambda b: _replace_first_record(b, "limitations", description="changed")),
)


def _side_leaf_cases():
    cases = []
    for side_name in ("left", "right"):
        prefix = f"contradiction.{side_name}"
        other_claim = "clm_spare"
        no_evidence = lambda: _contradiction_batch(left=_side("clm_left"), right=_side("clm_right"))
        cases.append(_leaf(f"{side_name}-claim-ref", f"{prefix}.claim_id", no_evidence, lambda b, side_name=side_name: _replace_side(b, side_name, claim_id=other_claim)))
        cases.append(_leaf(f"{side_name}-evidence-ref", f"{prefix}.evidence_id", _contradiction_batch, lambda b, side_name=side_name: _replace_side(b, side_name, evidence_id="evd_left_alt" if side_name == "left" else "evd_right_alt")))
        for field_name in ("object_key", "segment_key", "period_key", "metric_definition_key"):
            cases.append(_leaf(f"{side_name}-{field_name}", f"{prefix}.{field_name}", _contradiction_batch, lambda b, side_name=side_name, field_name=field_name: _replace_side(b, side_name, **{field_name: "changed"})))
    return tuple(cases)


SIDE_LEAF_CASES = _side_leaf_cases()


def _result_identity_pair():
    base = EvaluationBatch("bat_identity", (_limited(),))
    limitation = replace(base.results[0].limitations[0], related_result_ids=("res_other",))
    changed = replace(base.results[0], result_id="res_other", limitations=(limitation,))
    return base, replace(base, results=(changed,))


def _claim_identity_pair():
    base = _contradiction_batch(left=_side("clm_left"), right=_side("clm_right"))
    current = base.results[0]
    renamed = replace(current.claims[0], claim_id="clm_left_new")
    changed = _replace_first_result(base, claims=(renamed, *current.claims[1:]))
    return base, _replace_side(changed, "left", claim_id="clm_left_new")


def _evidence_identity_pair():
    base = _contradiction_batch()
    current = base.results[0]
    renamed = replace(current.evidence[0], evidence_id="evd_left0")
    renamed_claim = replace(current.claims[0], evidence_ids=("evd_left0", "evd_left_alt"))
    changed = _replace_first_result(base, evidence=(renamed, *current.evidence[1:]), claims=(renamed_claim, *current.claims[1:]))
    return base, _replace_side(changed, "left", evidence_id="evd_left0")


def _assumption_identity_pair():
    base = _records_batch()
    changed = _replace_first_record(base, "assumptions", assumption_id="asm_new")
    return base, _replace_first_claim(changed, assumption_ids=("asm_new",))


def _limitation_identity_pair():
    base = _records_batch()
    changed = _replace_first_record(base, "limitations", limitation_id="lim_new")
    return base, _replace_first_claim(changed, limitation_ids=("lim_new",))


IDENTITY_PAIRS = {
    "batch-id": lambda: (batch(), replace(batch(), batch_id="bat_new")),
    "result-id": _result_identity_pair,
    "claim-id": _claim_identity_pair,
    "evidence-id": _evidence_identity_pair,
    "assumption-id": _assumption_identity_pair,
    "limitation-id": _limitation_identity_pair,
    "contradiction-id": lambda: (_contradiction_batch(), replace(_contradiction_batch(), contradictions=(replace(_contradiction_batch().contradictions[0], contradiction_id="ctr_new"),))),
}


IDENTITY_CLOSURES = {
    "batch-id": frozenset({"batch.batch_id"}),
    "result-id": frozenset({"batch.results[0].result_id", "batch.results[0].limitations[0].related_result_ids[0]"}),
    "claim-id": frozenset({"batch.results[0].claims[0].claim_id", "batch.contradictions[0].left.claim_id"}),
    "evidence-id": frozenset({"batch.results[0].evidence[0].evidence_id", "batch.results[0].claims[0].evidence_ids[0]", "batch.contradictions[0].left.evidence_id"}),
    "assumption-id": frozenset({"batch.results[0].assumptions[0].assumption_id", "batch.results[0].claims[0].assumption_ids[0]"}),
    "limitation-id": frozenset({"batch.results[0].limitations[0].limitation_id", "batch.results[0].claims[0].limitation_ids[0]"}),
    "contradiction-id": frozenset({"batch.contradictions[0].contradiction_id"}),
}


IDENTITY_CASES = tuple(
    FingerprintCase(case_id, source, lambda pair=pair: pair()[0], lambda pair=pair: pair()[1], category="identity", changed_paths=IDENTITY_CLOSURES[case_id])
    for case_id, source, pair in (
        ("batch-id", "batch.batch_id", IDENTITY_PAIRS["batch-id"]),
        ("result-id", "result.result_id", IDENTITY_PAIRS["result-id"]),
        ("claim-id", "claim.claim_id", IDENTITY_PAIRS["claim-id"]),
        ("evidence-id", "evidence.evidence_id", IDENTITY_PAIRS["evidence-id"]),
        ("assumption-id", "assumption.assumption_id", IDENTITY_PAIRS["assumption-id"]),
        ("limitation-id", "limitation.limitation_id", IDENTITY_PAIRS["limitation-id"]),
        ("contradiction-id", "contradiction.contradiction_id", IDENTITY_PAIRS["contradiction-id"]),
    )
)


def _membership_cases():
    return (
        FingerprintCase("results-membership", "batch.results", lambda: EvaluationBatch("bat_members", (_pass("res_a", "clm_a"),)), lambda: EvaluationBatch("bat_members", (_pass("res_a", "clm_a"), _pass("res_b", "clm_b"))), category="membership"),
        FingerprintCase("contradictions-membership", "batch.contradictions", lambda: EvaluationBatch("bat_members", (_pass("res_one", "clm_left"), _pass("res_two", "clm_right"))), lambda: EvaluationBatch("bat_members", (_pass("res_one", "clm_left"), _pass("res_two", "clm_right")), (ContradictionInput("ctr_one", _side("clm_left"), _side("clm_right")),)), category="membership"),
        _leaf("claims-membership", "result.claims", lambda: batch(), lambda b: _replace_first_result(b, claims=(*b.results[0].claims, claim("clm_two")))),
        _leaf("evidence-membership", "result.evidence", lambda: batch(), lambda b: _replace_first_result(b, evidence=(EvidenceRecord("evd_two", EvidenceSourceClass.UNKNOWN, "two"),))),
        _leaf("assumptions-membership", "result.assumptions", lambda: batch(), lambda b: _replace_first_result(b, assumptions=(AssumptionRecord("asm_two", "two", Materiality.NON_MATERIAL),))),
        _leaf("limitations-membership", "result.limitations", lambda: batch(), lambda b: _replace_first_result(b, limitations=(LimitationRecord("lim_two", LimitationReason.TOOL_LIMIT, Materiality.NON_MATERIAL, ("res_one",)),))),
    )


MEMBERSHIP_CASES = tuple(replace(x, category="membership") for x in _membership_cases())


def _order_pair(collection):
    ev = (EvidenceRecord("evd_a", EvidenceSourceClass.FIRST_PARTY, "a", UTC), EvidenceRecord("evd_b", EvidenceSourceClass.UNKNOWN, "b", UTC))
    asm = (AssumptionRecord("asm_a", "a", Materiality.MATERIAL), AssumptionRecord("asm_b", "b", Materiality.NON_MATERIAL))
    lim = (LimitationRecord("lim_a", LimitationReason.TOOL_LIMIT, Materiality.NON_MATERIAL, ("res_one",)), LimitationRecord("lim_b", LimitationReason.CAPABILITY_LIMIT, Materiality.NON_MATERIAL, ("res_one",)))
    claims = (claim("clm_a"), claim("clm_b"))
    values = {"claims": claims, "evidence": ev, "assumptions": asm, "limitations": lim}
    forward = batch(results=(result(claims=claims, evidence=ev, assumptions=asm, limitations=lim),))
    reverse = _replace_first_result(forward, **{collection: tuple(reversed(values[collection]))})
    return forward, reverse


def _id_order_pair(field_name):
    current = claim("clm_child", confidence=Confidence.LOW, lineage_type=ClaimLineageType.DERIVES, parent_claim_ids=("clm_parent_a", "clm_parent_b"), evidence_ids=("evd_a", "evd_b"), assumption_ids=("asm_a", "asm_b"), limitation_ids=("lim_a", "lim_b"))
    records = result(
        claims=(claim("clm_parent_a", confidence=Confidence.MEDIUM), claim("clm_parent_b", confidence=Confidence.MEDIUM), current),
        evidence=(EvidenceRecord("evd_a", EvidenceSourceClass.UNKNOWN, "a"), EvidenceRecord("evd_b", EvidenceSourceClass.UNKNOWN, "b")),
        assumptions=(AssumptionRecord("asm_a", "a", Materiality.NON_MATERIAL), AssumptionRecord("asm_b", "b", Materiality.NON_MATERIAL)),
        limitations=(LimitationRecord("lim_a", LimitationReason.TOOL_LIMIT, Materiality.NON_MATERIAL, ("res_one",)), LimitationRecord("lim_b", LimitationReason.CAPABILITY_LIMIT, Materiality.NON_MATERIAL, ("res_one",))),
    )
    baseline = batch(results=(records,))
    changed_claim = replace(current, **{field_name: tuple(reversed(getattr(current, field_name)))})
    changed = _replace_first_result(baseline, claims=(*records.claims[:2], changed_claim))
    return baseline, changed


def _order_cases():
    result_a, result_b = _pass("res_a", "clm_a"), _pass("res_b", "clm_b")
    result_pair = lambda: (EvaluationBatch("bat_order", (result_a, result_b)), EvaluationBatch("bat_order", (result_b, result_a)))
    contradiction_pair = lambda: (
        EvaluationBatch("bat_order", (result_a, result_b), (ContradictionInput("ctr_a", _side("clm_a"), _side("clm_b")), ContradictionInput("ctr_b", _side("clm_a"), _side("clm_b")))),
        EvaluationBatch("bat_order", (result_a, result_b), (ContradictionInput("ctr_b", _side("clm_a"), _side("clm_b")), ContradictionInput("ctr_a", _side("clm_a"), _side("clm_b")))),
    )
    cases = [FingerprintCase("results-order", "batch.results", lambda: result_pair()[0], lambda: result_pair()[1], True, "order", element_count=2)]
    for name in ("claims", "evidence", "assumptions", "limitations"):
        cases.append(FingerprintCase(f"{name}-order", f"result.{name}", lambda name=name: _order_pair(name)[0], lambda name=name: _order_pair(name)[1], True, "order", element_count=2))
    cases.append(FingerprintCase("contradictions-order", "batch.contradictions", lambda: contradiction_pair()[0], lambda: contradiction_pair()[1], True, "order", element_count=2))
    cases.extend((
        FingerprintCase("failure-reasons-order", "result.failure_reasons", lambda: batch(results=(_fail(reasons=[FailureReason.AUTHORITY_VIOLATION, FailureReason.MODULE_DECLARED_FAILURE]),)), lambda: batch(results=(_fail(reasons=[FailureReason.MODULE_DECLARED_FAILURE, FailureReason.AUTHORITY_VIOLATION]),)), True, "order", element_count=2),
        FingerprintCase("blocking-reasons-order", "result.blocking_reasons", lambda: batch(results=(_blocked(reasons=[BlockingReason.MISSING_CAPABILITY, BlockingReason.TOOL_UNAVAILABLE]),)), lambda: batch(results=(_blocked(reasons=[BlockingReason.TOOL_UNAVAILABLE, BlockingReason.MISSING_CAPABILITY]),)), True, "order", element_count=2),
        FingerprintCase("handoffs-order", "result.handoff_module_ids", lambda: batch(results=(_pass(handoff_module_ids=[ModuleId.POSITIONING, ModuleId.EXPERIMENTS]),)), lambda: batch(results=(_pass(handoff_module_ids=[ModuleId.EXPERIMENTS, ModuleId.POSITIONING]),)), True, "order", element_count=2),
    ))
    for field_name in ("parent_claim_ids", "evidence_ids", "assumption_ids", "limitation_ids"):
        cases.append(FingerprintCase(f"{field_name}-order", f"claim.{field_name}", lambda field_name=field_name: _id_order_pair(field_name)[0], lambda field_name=field_name: _id_order_pair(field_name)[1], True, "order", element_count=2))
    side_pair = lambda: (_contradiction_batch(), replace(_contradiction_batch(), contradictions=(replace(_contradiction_batch().contradictions[0], left=_contradiction_batch().contradictions[0].right, right=_contradiction_batch().contradictions[0].left),)))
    cases.append(FingerprintCase("contradiction-side-position", "contradiction.left/right", lambda: side_pair()[0], lambda: side_pair()[1], False, "order", element_count=2))
    return tuple(cases)


ORDER_CASES = _order_cases()


def _status_pair():
    base = batch()
    limitation = LimitationRecord("lim_status", LimitationReason.TOOL_LIMIT, Materiality.MATERIAL, ("res_one",), ("clm_one",))
    changed_claim = replace(base.results[0].claims[0], limitation_ids=("lim_status",))
    changed = _replace_first_result(base, module_status=ModuleResultStatus.PASS_WITH_LIMITATIONS, claims=(changed_claim,), limitations=(limitation,))
    return base, changed


def _limitation_materiality_pair():
    base = _records_batch()
    changed = _replace_first_record(base, "limitations", materiality=Materiality.MATERIAL)
    return base, _replace_first_result(changed, module_status=ModuleResultStatus.PASS_WITH_LIMITATIONS)


COHERENCE_CASES = (
    FingerprintCase(
        "module-status-coherence", "result.module_status", lambda: _status_pair()[0], lambda: _status_pair()[1],
        category="coherence", changed_paths=frozenset({
            "batch.results[0].module_status", "batch.results[0].claims[0].limitation_ids",
            "batch.results[0].limitations",
        }),
    ),
    FingerprintCase(
        "limitation-materiality-coherence", "limitation.materiality", lambda: _limitation_materiality_pair()[0], lambda: _limitation_materiality_pair()[1],
        category="coherence", changed_paths=frozenset({
            "batch.results[0].module_status", "batch.results[0].limitations[0].materiality",
        }),
    ),
)


ALL_CASES = LEAF_CASES + SIDE_LEAF_CASES + IDENTITY_CASES + MEMBERSHIP_CASES + ORDER_CASES + COHERENCE_CASES


CALLER_FINGERPRINT_LEAVES = frozenset({
    "batch.batch_id", "batch.evaluation_at", "result.result_id", "result.module_id", "result.module_status",
    "result.failure_reasons", "result.blocking_reasons", "result.evidence_sufficiency", "result.handoff_module_ids",
    "claim.claim_id", "claim.declared_output_name", "claim.claim_type", "claim.confidence", "claim.authority_status", "claim.value",
    "claim.lineage_type", "claim.parent_claim_ids", "claim.evidence_ids", "claim.assumption_ids", "claim.limitation_ids",
    "evidence.evidence_id", "evidence.source_class", "evidence.provenance", "evidence.observed_at",
    "assumption.assumption_id", "assumption.description", "assumption.materiality",
    "limitation.limitation_id", "limitation.reason", "limitation.materiality", "limitation.related_result_ids",
    "limitation.related_claim_ids", "limitation.related_contradiction_ids", "limitation.description",
    "contradiction.contradiction_id",
    *(f"contradiction.{side}.{field}" for side in ("left", "right") for field in ("claim_id", "evidence_id", "object_key", "segment_key", "period_key", "metric_definition_key")),
})


COLLECTION_MEMBERSHIP = frozenset({"batch.results", "batch.contradictions", "result.claims", "result.evidence", "result.assumptions", "result.limitations"})
COLLECTION_ORDER = frozenset({
    "batch.results", "batch.contradictions", "result.claims", "result.evidence", "result.assumptions", "result.limitations",
    "result.failure_reasons", "result.blocking_reasons", "result.handoff_module_ids", "claim.parent_claim_ids", "claim.evidence_ids",
    "claim.assumption_ids", "claim.limitation_ids", "contradiction.left/right",
})
STRUCTURAL_COVERAGE = {
    "contradiction.left": frozenset(f"contradiction.left.{field}" for field in ("claim_id", "evidence_id", "object_key", "segment_key", "period_key", "metric_definition_key")),
    "contradiction.right": frozenset(f"contradiction.right.{field}" for field in ("claim_id", "evidence_id", "object_key", "segment_key", "period_key", "metric_definition_key")),
}
REFERENCE_IDENTITIES = frozenset({"batch.batch_id", "result.result_id", "claim.claim_id", "evidence.evidence_id", "assumption.assumption_id", "limitation.limitation_id", "contradiction.contradiction_id"})


def _diff_paths(left, right, path="batch"):
    if type(left) is not type(right):
        return {path}
    if is_dataclass(left):
        changed = set()
        for field in fields(left):
            if field.name == "batch_fingerprint":
                continue
            changed |= _diff_paths(getattr(left, field.name), getattr(right, field.name), f"{path}.{field.name}")
        return changed
    if isinstance(left, tuple):
        if len(left) != len(right):
            return {path}
        changed = set()
        for index, (a, b) in enumerate(zip(left, right)):
            changed |= _diff_paths(a, b, f"{path}[{index}]")
        return changed
    if isinstance(left, (frozenset, Enum)):
        return set() if left == right else {path}
    return set() if left == right else {path}


def assert_evaluator_valid_fingerprint_case(case):
    baseline = case.baseline()
    mutated = case.mutated()
    if case.equal:
        assert case.category == "order" and case.element_count >= 2
    else:
        assert baseline != mutated, f"{case.case_id} is a no-op"
    evaluator = QualityGateEvaluator()
    baseline_output = evaluator.evaluate(baseline)
    mutated_output = evaluator.evaluate(mutated)
    assert all(output.execution_readiness is ExecutionReadiness.PLANNING_ONLY for output in (baseline_output, mutated_output))
    if case.equal:
        assert baseline.batch_fingerprint == mutated.batch_fingerprint
    else:
        assert baseline.batch_fingerprint != mutated.batch_fingerprint
    if case.category == "identity":
        assert _diff_paths(baseline, mutated) == set(case.changed_paths)
    elif case.category == "leaf":
        assert len(_diff_paths(baseline, mutated)) == 1
    elif case.category == "coherence":
        assert _diff_paths(baseline, mutated) == set(case.changed_paths)


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda case: case.case_id)
def test_declared_fingerprint_case_is_evaluator_valid(case):
    assert_evaluator_valid_fingerprint_case(case)


def test_fingerprint_coverage_manifest_is_independent_complete_and_unique():
    ids = [case.case_id for case in ALL_CASES]
    assert len(ids) == len(set(ids))
    sources = {case.source for case in ALL_CASES}
    assert CALLER_FINGERPRINT_LEAVES <= sources
    assert REFERENCE_IDENTITIES == {case.source for case in IDENTITY_CASES}
    assert COLLECTION_MEMBERSHIP == {case.source for case in MEMBERSHIP_CASES}
    assert COLLECTION_ORDER == {case.source for case in ORDER_CASES}
    tested_side_leaves = {case.source for case in SIDE_LEAF_CASES}
    assert all(descendants <= tested_side_leaves for descendants in STRUCTURAL_COVERAGE.values())
    mutation_signatures = [(case.source, case.category, case.changed_paths) for case in ALL_CASES]
    assert len(mutation_signatures) == len(set(mutation_signatures))
    assert "batch.batch_fingerprint" not in sources
    assert "propagated_claim_contexts" not in sources


def test_all_four_fixed_vectors_remain_unchanged():
    from app.marketing_orchestrator.quality_gates.canonical import derive_id

    assert batch().batch_fingerprint == "20c9fb5190f14cfdbf629821ed4a3a48a257a4960c6b9d3cb1ca8d42beb9a33b"
    simple = EvaluationBatch(
        "bat_one", (result(claims=(claim("clm_left"), claim("clm_right"))),),
        (ContradictionInput("ctr_one", _side("clm_left", object_key="o", segment_key="s", period_key="p", metric_definition_key="m"), _side("clm_right", object_key="o", segment_key="s", period_key="p", metric_definition_key="m")),),
    )
    assert simple.batch_fingerprint == "578850d498e6d6e28673e7bd8274138af3266a713bb3d2148d9363189e64ff99"
    limitation, _ = derive_id("lim", ("quality-gates-v1", "limitation", "0" * 64, "res_one", "ctr_one", "UNRESOLVED_CONTRADICTION"))
    exclusion, _ = derive_id("exc", ("quality-gates-v1", "exclusion", "0" * 64, "CLAIM", "", "clm_one", "UNRESOLVED_CONTRADICTION", "ctr_one"))
    assert limitation == "lim_2b42fd3a91882bc24469ecfa3334aed0"
    assert exclusion == "exc_a2e97bf393be35ca457a154117ceb728"
