from collections import Counter
from dataclasses import dataclass, fields, is_dataclass, replace
from datetime import timedelta
from enum import Enum
import hashlib
import json
import re
from typing import Callable

import pytest

from app.marketing_orchestrator.quality_gates import *
from app.module_registry import ModuleId, ModuleResultStatus
from tests.quality_gate_helpers import UTC, batch, claim, result


BatchFactory = Callable[[], EvaluationBatch]


class EvidenceCatalogError(AssertionError):
    pass


@dataclass(frozen=True)
class MembershipExpectation:
    path: str
    identity_field: str
    baseline_ids: tuple[str, ...]
    mutated_ids: tuple[str, ...]
    added_ids: frozenset[str] = frozenset()
    removed_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RawOrderingInput:
    fields: tuple[tuple[str, object], ...]

    def value(self, path):
        values = dict(self.fields)
        if len(values) != len(self.fields) or path not in values:
            raise EvidenceCatalogError("raw ordering fields must be unique and contain the target")
        return values[path]


@dataclass(frozen=True)
class OrderingWitness:
    target_path: str
    baseline_raw: RawOrderingInput
    mutated_raw: RawOrderingInput
    builder: Callable[[RawOrderingInput], EvaluationBatch]


@dataclass(frozen=True)
class FingerprintCase:
    case_id: str
    source: str
    baseline: BatchFactory
    mutated: BatchFactory
    equal: bool = False
    category: str = "leaf"
    expected_changed_paths: frozenset[str] = frozenset()
    membership: MembershipExpectation | None = None
    ordering: OrderingWitness | None = None
    element_count: int | None = None


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


def _leaf(case_id, source, expected_changed_path, baseline, mutate):
    return FingerprintCase(
        case_id, source, baseline, lambda: mutate(baseline()),
        expected_changed_paths=frozenset({expected_changed_path}),
    )


LEAF_CASES = (
    _leaf("evaluation-at", "batch.evaluation_at", "batch.evaluation_at", lambda: batch(evaluation_at=UTC), lambda b: replace(b, evaluation_at=UTC + timedelta(seconds=1))),
    _leaf("module-id", "result.module_id", "batch.results[0].module_id", lambda: batch(results=(_fail(),)), lambda b: _replace_first_result(b, module_id=ModuleId.MENTOR)),
    _leaf("failure-reasons", "result.failure_reasons", "batch.results[0].failure_reasons", lambda: batch(results=(_fail(),)), lambda b: _replace_first_result(b, failure_reasons={FailureReason.AUTHORITY_VIOLATION})),
    _leaf("blocking-reasons", "result.blocking_reasons", "batch.results[0].blocking_reasons", lambda: batch(results=(_blocked(),)), lambda b: _replace_first_result(b, blocking_reasons={BlockingReason.MISSING_CAPABILITY})),
    _leaf("evidence-sufficiency", "result.evidence_sufficiency", "batch.results[0].evidence_sufficiency", lambda: batch(results=(_limited(),)), lambda b: _replace_first_result(b, evidence_sufficiency=EvidenceSufficiency.SUFFICIENT)),
    _leaf("handoff-membership", "result.handoff_module_ids", "batch.results[0].handoff_module_ids", lambda: batch(results=(_pass(handoff_module_ids={ModuleId.POSITIONING}),)), lambda b: _replace_first_result(b, handoff_module_ids={ModuleId.EXPERIMENTS})),
    _leaf("declared-output", "claim.declared_output_name", "batch.results[0].claims[0].declared_output_name", lambda: batch(), lambda b: _replace_first_claim(b, declared_output_name="main_growth_constraint")),
    _leaf("claim-type", "claim.claim_type", "batch.results[0].claims[0].claim_type", lambda: batch(), lambda b: _replace_first_claim(b, claim_type=ClaimType.INFERENCE)),
    _leaf("confidence", "claim.confidence", "batch.results[0].claims[0].confidence", lambda: batch(), lambda b: _replace_first_claim(b, confidence=Confidence.MEDIUM)),
    _leaf("authority", "claim.authority_status", "batch.results[0].claims[0].authority_status", lambda: batch(), lambda b: _replace_first_claim(b, authority_status=AuthorityStatus.REQUIRES_REVIEW)),
    _leaf("claim-value", "claim.value", "batch.results[0].claims[0].value", lambda: batch(), lambda b: _replace_first_claim(b, value="changed")),
    _leaf("lineage-type", "claim.lineage_type", "batch.results[0].claims[2].lineage_type", lambda: _lineage_batch(), lambda b: _replace_first_result(b, claims=(*b.results[0].claims[:2], replace(b.results[0].claims[2], lineage_type=ClaimLineageType.REFORMULATES)))),
    _leaf("parent-ids", "claim.parent_claim_ids", "batch.results[0].claims[2].parent_claim_ids[0]", lambda: _lineage_batch(), lambda b: _replace_first_result(b, claims=(*b.results[0].claims[:2], replace(b.results[0].claims[2], parent_claim_ids=("clm_parent_b",))))),
    _leaf("claim-evidence-ids", "claim.evidence_ids", "batch.results[0].claims[0].evidence_ids", _records_batch, lambda b: _replace_first_claim(b, evidence_ids=())),
    _leaf("claim-assumption-ids", "claim.assumption_ids", "batch.results[0].claims[0].assumption_ids", _records_batch, lambda b: _replace_first_claim(b, assumption_ids=())),
    _leaf("claim-limitation-ids", "claim.limitation_ids", "batch.results[0].claims[0].limitation_ids", _records_batch, lambda b: _replace_first_claim(b, limitation_ids=())),
    _leaf("evidence-source", "evidence.source_class", "batch.results[0].evidence[0].source_class", _records_batch, lambda b: _replace_first_record(b, "evidence", source_class=EvidenceSourceClass.UNKNOWN)),
    _leaf("evidence-provenance", "evidence.provenance", "batch.results[0].evidence[0].provenance", _records_batch, lambda b: _replace_first_record(b, "evidence", provenance="changed")),
    _leaf("evidence-observed-at", "evidence.observed_at", "batch.results[0].evidence[0].observed_at", _records_batch, lambda b: _replace_first_record(b, "evidence", observed_at=UTC + timedelta(seconds=1))),
    _leaf("assumption-description", "assumption.description", "batch.results[0].assumptions[0].description", _records_batch, lambda b: _replace_first_record(b, "assumptions", description="changed")),
    _leaf("assumption-materiality", "assumption.materiality", "batch.results[0].assumptions[0].materiality", _records_batch, lambda b: _replace_first_record(b, "assumptions", materiality=Materiality.NON_MATERIAL)),
    _leaf("limitation-reason", "limitation.reason", "batch.results[0].limitations[0].reason", _records_batch, lambda b: _replace_first_record(b, "limitations", reason=LimitationReason.CAPABILITY_LIMIT)),
    _leaf("limitation-result-refs", "limitation.related_result_ids", "batch.results[0].limitations[0].related_result_ids[0]", _related_batch, lambda b: _replace_first_record(b, "limitations", related_result_ids=("res_b",))),
    _leaf("limitation-claim-refs", "limitation.related_claim_ids", "batch.results[0].limitations[0].related_claim_ids[0]", _related_batch, lambda b: _replace_first_record(b, "limitations", related_claim_ids=("clm_b",))),
    _leaf("limitation-contradiction-refs", "limitation.related_contradiction_ids", "batch.results[0].limitations[0].related_contradiction_ids[0]", lambda: _related_batch(contradiction_ref=("ctr_a",)), lambda b: _replace_first_record(b, "limitations", related_contradiction_ids=("ctr_b",))),
    _leaf("limitation-description", "limitation.description", "batch.results[0].limitations[0].description", _records_batch, lambda b: _replace_first_record(b, "limitations", description="changed")),
)


def _side_leaf_cases():
    cases = []
    for side_name in ("left", "right"):
        prefix = f"contradiction.{side_name}"
        other_claim = "clm_spare"
        no_evidence = lambda: _contradiction_batch(left=_side("clm_left"), right=_side("clm_right"))
        cases.append(_leaf(f"{side_name}-claim-ref", f"{prefix}.claim_id", f"batch.contradictions[0].{side_name}.claim_id", no_evidence, lambda b, side_name=side_name: _replace_side(b, side_name, claim_id=other_claim)))
        cases.append(_leaf(f"{side_name}-evidence-ref", f"{prefix}.evidence_id", f"batch.contradictions[0].{side_name}.evidence_id", _contradiction_batch, lambda b, side_name=side_name: _replace_side(b, side_name, evidence_id="evd_left_alt" if side_name == "left" else "evd_right_alt")))
        for field_name in ("object_key", "segment_key", "period_key", "metric_definition_key"):
            cases.append(_leaf(f"{side_name}-{field_name}", f"{prefix}.{field_name}", f"batch.contradictions[0].{side_name}.{field_name}", _contradiction_batch, lambda b, side_name=side_name, field_name=field_name: _replace_side(b, side_name, **{field_name: "changed"})))
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
    FingerprintCase(case_id, source, lambda pair=pair: pair()[0], lambda pair=pair: pair()[1], category="identity", expected_changed_paths=IDENTITY_CLOSURES[case_id])
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
    def case(case_id, source, path, identity_field, baseline_ids, mutated_ids, baseline, mutated):
        return FingerprintCase(
            case_id, source, baseline, mutated, category="membership",
            expected_changed_paths=frozenset({path}),
            membership=MembershipExpectation(
                path, identity_field, baseline_ids, mutated_ids,
                frozenset(set(mutated_ids) - set(baseline_ids)),
                frozenset(set(baseline_ids) - set(mutated_ids)),
            ),
        )
    return (
        case("results-membership", "batch.results", "batch.results", "result_id", ("res_a",), ("res_a", "res_b"), lambda: EvaluationBatch("bat_members", (_pass("res_a", "clm_a"),)), lambda: EvaluationBatch("bat_members", (_pass("res_a", "clm_a"), _pass("res_b", "clm_b")))),
        case("contradictions-membership", "batch.contradictions", "batch.contradictions", "contradiction_id", (), ("ctr_one",), lambda: EvaluationBatch("bat_members", (_pass("res_one", "clm_left"), _pass("res_two", "clm_right"))), lambda: EvaluationBatch("bat_members", (_pass("res_one", "clm_left"), _pass("res_two", "clm_right")), (ContradictionInput("ctr_one", _side("clm_left"), _side("clm_right")),))),
        case("claims-membership", "result.claims", "batch.results[0].claims", "claim_id", ("clm_one",), ("clm_one", "clm_two"), batch, lambda: _replace_first_result(batch(), claims=(*batch().results[0].claims, claim("clm_two")))),
        case("evidence-membership", "result.evidence", "batch.results[0].evidence", "evidence_id", (), ("evd_two",), batch, lambda: _replace_first_result(batch(), evidence=(EvidenceRecord("evd_two", EvidenceSourceClass.UNKNOWN, "two"),))),
        case("assumptions-membership", "result.assumptions", "batch.results[0].assumptions", "assumption_id", (), ("asm_two",), batch, lambda: _replace_first_result(batch(), assumptions=(AssumptionRecord("asm_two", "two", Materiality.NON_MATERIAL),))),
        case("limitations-membership", "result.limitations", "batch.results[0].limitations", "limitation_id", (), ("lim_two",), batch, lambda: _replace_first_result(batch(), limitations=(LimitationRecord("lim_two", LimitationReason.TOOL_LIMIT, Materiality.NON_MATERIAL, ("res_one",)),))),
    )


MEMBERSHIP_CASES = _membership_cases()


def _ordering_case(case_id, source, values, builder, *, equal=True, extra_fields=()):
    baseline_raw = RawOrderingInput(((source, tuple(values)), *extra_fields))
    mutated_raw = RawOrderingInput(((source, tuple(reversed(values))), *extra_fields))
    witness = OrderingWitness(source, baseline_raw, mutated_raw, builder)
    return FingerprintCase(
        case_id, source,
        lambda witness=witness: witness.builder(witness.baseline_raw),
        lambda witness=witness: witness.builder(witness.mutated_raw),
        equal=equal, category="order", ordering=witness,
    )


def _nested_order_builder(collection):
    evidence = (EvidenceRecord("evd_a", EvidenceSourceClass.FIRST_PARTY, "a", UTC), EvidenceRecord("evd_b", EvidenceSourceClass.UNKNOWN, "b", UTC))
    assumptions = (AssumptionRecord("asm_a", "a", Materiality.MATERIAL), AssumptionRecord("asm_b", "b", Materiality.NON_MATERIAL))
    limitations = (LimitationRecord("lim_a", LimitationReason.TOOL_LIMIT, Materiality.NON_MATERIAL, ("res_one",)), LimitationRecord("lim_b", LimitationReason.CAPABILITY_LIMIT, Materiality.NON_MATERIAL, ("res_one",)))
    claims = (claim("clm_a"), claim("clm_b"))
    defaults = {"claims": claims, "evidence": evidence, "assumptions": assumptions, "limitations": limitations}

    def builder(raw):
        values = dict(defaults)
        values[collection] = raw.value(f"result.{collection}")
        return batch(results=(result(**values),))

    return defaults[collection], builder


def _id_order_builder(field_name):
    evidence = (EvidenceRecord("evd_a", EvidenceSourceClass.UNKNOWN, "a"), EvidenceRecord("evd_b", EvidenceSourceClass.UNKNOWN, "b"))
    assumptions = (AssumptionRecord("asm_a", "a", Materiality.NON_MATERIAL), AssumptionRecord("asm_b", "b", Materiality.NON_MATERIAL))
    limitations = (LimitationRecord("lim_a", LimitationReason.TOOL_LIMIT, Materiality.NON_MATERIAL, ("res_one",)), LimitationRecord("lim_b", LimitationReason.CAPABILITY_LIMIT, Materiality.NON_MATERIAL, ("res_one",)))
    defaults = {
        "parent_claim_ids": ("clm_parent_a", "clm_parent_b"), "evidence_ids": ("evd_a", "evd_b"),
        "assumption_ids": ("asm_a", "asm_b"), "limitation_ids": ("lim_a", "lim_b"),
    }

    def builder(raw):
        child_fields = dict(defaults)
        child_fields[field_name] = raw.value(f"claim.{field_name}")
        child = claim("clm_child", confidence=Confidence.LOW, lineage_type=ClaimLineageType.DERIVES, **child_fields)
        module_result = result(
            claims=(claim("clm_parent_a", confidence=Confidence.MEDIUM), claim("clm_parent_b", confidence=Confidence.MEDIUM), child),
            evidence=evidence, assumptions=assumptions, limitations=limitations,
        )
        return batch(results=(module_result,))

    return defaults[field_name], builder


def _order_cases():
    result_a, result_b = _pass("res_a", "clm_a"), _pass("res_b", "clm_b")
    cases = [_ordering_case("results-order", "batch.results", (result_a, result_b), lambda raw: EvaluationBatch("bat_order", raw.value("batch.results")))]
    for name in ("claims", "evidence", "assumptions", "limitations"):
        values, builder = _nested_order_builder(name)
        cases.append(_ordering_case(f"{name}-order", f"result.{name}", values, builder))
    contradictions = (ContradictionInput("ctr_a", _side("clm_a"), _side("clm_b")), ContradictionInput("ctr_b", _side("clm_a"), _side("clm_b")))
    cases.append(_ordering_case("contradictions-order", "batch.contradictions", contradictions, lambda raw: EvaluationBatch("bat_order", (result_a, result_b), raw.value("batch.contradictions"))))
    cases.extend((
        _ordering_case("failure-reasons-order", "result.failure_reasons", (FailureReason.AUTHORITY_VIOLATION, FailureReason.MODULE_DECLARED_FAILURE), lambda raw: batch(results=(_fail(reasons=raw.value("result.failure_reasons")),))),
        _ordering_case("blocking-reasons-order", "result.blocking_reasons", (BlockingReason.MISSING_CAPABILITY, BlockingReason.TOOL_UNAVAILABLE), lambda raw: batch(results=(_blocked(reasons=raw.value("result.blocking_reasons")),))),
        _ordering_case("handoffs-order", "result.handoff_module_ids", (ModuleId.POSITIONING, ModuleId.EXPERIMENTS), lambda raw: batch(results=(_pass(handoff_module_ids=raw.value("result.handoff_module_ids")),))),
    ))
    for field_name in ("parent_claim_ids", "evidence_ids", "assumption_ids", "limitation_ids"):
        values, builder = _id_order_builder(field_name)
        cases.append(_ordering_case(f"{field_name}-order", f"claim.{field_name}", values, builder))
    base = _contradiction_batch()
    sides = (base.contradictions[0].left, base.contradictions[0].right)
    cases.append(_ordering_case(
        "contradiction-side-position", "contradiction.left/right", sides,
        lambda raw: replace(base, contradictions=(replace(base.contradictions[0], left=raw.value("contradiction.left/right")[0], right=raw.value("contradiction.left/right")[1]),)),
        equal=False,
    ))
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
        category="coherence", expected_changed_paths=frozenset({
            "batch.results[0].module_status", "batch.results[0].claims[0].limitation_ids",
            "batch.results[0].limitations",
        }),
    ),
    FingerprintCase(
        "limitation-materiality-coherence", "limitation.materiality", lambda: _limitation_materiality_pair()[0], lambda: _limitation_materiality_pair()[1],
        category="coherence", expected_changed_paths=frozenset({
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
    "contradiction.left": frozenset(f"batch.contradictions[0].left.{field}" for field in ("claim_id", "evidence_id", "object_key", "segment_key", "period_key", "metric_definition_key")),
    "contradiction.right": frozenset(f"batch.contradictions[0].right.{field}" for field in ("claim_id", "evidence_id", "object_key", "segment_key", "period_key", "metric_definition_key")),
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


def _require(condition, message):
    if not condition:
        raise EvidenceCatalogError(message)


def _stable(value):
    if is_dataclass(value):
        return [
            "record", type(value).__name__,
            [[field.name, _stable(getattr(value, field.name))] for field in fields(value) if field.name != "batch_fingerprint"],
        ]
    if isinstance(value, Enum):
        return ["enum", type(value).__name__, value.value]
    if isinstance(value, tuple):
        return ["tuple", [_stable(item) for item in value]]
    if isinstance(value, frozenset):
        items = [_stable(item) for item in value]
        return ["frozenset", sorted(items, key=lambda item: json.dumps(item, sort_keys=True))]
    if hasattr(value, "isoformat") and type(value).__module__ == "datetime":
        return ["datetime", value.isoformat()]
    return [type(value).__name__, value]


def _stable_text(value):
    return json.dumps(_stable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _get_path(value, path):
    tokens = re.findall(r"([a-z_]+)|\[(\d+)\]", path)
    current = value
    for name, index in tokens:
        if name:
            if name == "batch" and current is value:
                continue
            current = getattr(current, name)
        else:
            current = current[int(index)]
    return current


def _logical_path(path):
    path = re.sub(r"\[\d+\]", "", path)
    for prefix, logical in (
        ("batch.results.claims.", "claim."),
        ("batch.results.evidence.", "evidence."),
        ("batch.results.assumptions.", "assumption."),
        ("batch.results.limitations.", "limitation."),
        ("batch.results.", "result."),
        ("batch.contradictions.", "contradiction."),
    ):
        if path.startswith(prefix):
            return logical + path[len(prefix):]
    return path


def _raw_fields(raw):
    values = dict(raw.fields)
    _require(len(values) == len(raw.fields), "raw ordering field names must be unique")
    return values


def _validate_ordering_witness(case):
    witness = case.ordering
    _require(witness is not None, "ordering evidence requires a raw witness")
    _require(case.element_count in (None, 0), "legacy element_count metadata is forbidden")
    _require(witness.target_path == case.source, "ordering witness target must match case source")
    before_fields = _raw_fields(witness.baseline_raw)
    after_fields = _raw_fields(witness.mutated_raw)
    _require(set(before_fields) == set(after_fields), "raw ordering field membership changed")
    raw_diffs = {name for name in before_fields if _stable_text(before_fields[name]) != _stable_text(after_fields[name])}
    _require(raw_diffs == {witness.target_path}, "only the declared raw ordering path may change")
    before = before_fields[witness.target_path]
    after = after_fields[witness.target_path]
    _require(type(before) is tuple and type(after) is tuple, "raw ordering targets must be exact tuples")
    _require(len(before) >= 2 and len(after) >= 2, "ordering evidence requires at least two elements")
    before_keys = tuple(_stable_text(item) for item in before)
    after_keys = tuple(_stable_text(item) for item in after)
    _require(len(set(before_keys)) >= 2, "ordering evidence requires at least two distinct elements")
    _require(after_keys == tuple(reversed(before_keys)), "mutated raw sequence must be the exact reverse")
    _require(before_keys != after_keys, "raw ordering must change")
    _require(Counter(before_keys) == Counter(after_keys), "raw ordering membership must remain unchanged")
    built_before = witness.builder(witness.baseline_raw)
    built_after = witness.builder(witness.mutated_raw)
    supplied_before = case.baseline()
    supplied_after = case.mutated()
    _require(_stable_text(supplied_before) == _stable_text(built_before), "baseline batch was not built from its raw witness")
    _require(_stable_text(supplied_after) == _stable_text(built_after), "mutated batch was not built from its raw witness")
    if not case.equal:
        _require(supplied_before != supplied_after, "order-significant caller trees must remain different")
    return supplied_before, supplied_after


def _validate_membership(case, baseline, mutated, actual_paths):
    expected = case.membership
    _require(expected is not None, "membership evidence requires a declaration")
    _require(actual_paths == set(case.expected_changed_paths) == {expected.path}, "membership diff path does not match its declaration")
    _require(_logical_path(expected.path) == case.source, "membership source label does not match its actual path")
    before = _get_path(baseline, expected.path)
    after = _get_path(mutated, expected.path)
    _require(type(before) is tuple and type(after) is tuple, "membership target must be an exact tuple")
    before_ids = tuple(getattr(item, expected.identity_field) for item in before)
    after_ids = tuple(getattr(item, expected.identity_field) for item in after)
    _require(before_ids == expected.baseline_ids and after_ids == expected.mutated_ids, "actual membership identities do not match the declaration")
    added = frozenset(after_ids) - frozenset(before_ids)
    removed = frozenset(before_ids) - frozenset(after_ids)
    _require(added == expected.added_ids and removed == expected.removed_ids, "actual membership delta does not match the declaration")
    _require(len(added) + len(removed) == 1, "membership evidence must add or remove exactly one element")
    before_records = {getattr(item, expected.identity_field): _stable_text(item) for item in before}
    after_records = {getattr(item, expected.identity_field): _stable_text(item) for item in after}
    _require(all(before_records[item] == after_records[item] for item in set(before_ids) & set(after_ids)), "existing membership content changed")


def _mutation_signature(case, baseline, mutated, actual_paths):
    changed_values = [
        [path, _stable(_get_path(baseline, path)), _stable(_get_path(mutated, path))]
        for path in sorted(actual_paths)
    ]
    raw = None
    if case.ordering is not None:
        raw = [_stable(case.ordering.baseline_raw), _stable(case.ordering.mutated_raw)]
    payload = [_stable(baseline), _stable(mutated), sorted(actual_paths), changed_values, raw]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_fingerprint_case(case):
    if case.category == "order":
        baseline, mutated = _validate_ordering_witness(case)
    else:
        _require(case.ordering is None, "non-ordering evidence must not carry an ordering witness")
        _require(case.element_count in (None, 0), "legacy element_count metadata is forbidden")
        baseline = case.baseline()
        mutated = case.mutated()
        _require(baseline != mutated, f"{case.case_id} is a semantic no-op")
    actual_paths = _diff_paths(baseline, mutated)
    if case.category == "leaf":
        _require(actual_paths == set(case.expected_changed_paths) and len(actual_paths) == 1, "isolated leaf paths do not match their declaration")
        _require(_logical_path(next(iter(actual_paths))) == case.source, "leaf source label does not match the actual mutation")
    elif case.category == "identity":
        _require(actual_paths == set(case.expected_changed_paths), "identity closure does not match its declaration")
        _require(case.source in {_logical_path(path) for path in actual_paths}, "identity source is absent from its actual closure")
    elif case.category == "membership":
        _validate_membership(case, baseline, mutated, actual_paths)
    elif case.category == "coherence":
        _require(actual_paths == set(case.expected_changed_paths), "coherence closure does not match its declaration")
        _require(case.source in {_logical_path(path) for path in actual_paths}, "coherence source is absent from its actual closure")
    elif case.category != "order":
        raise EvidenceCatalogError(f"unknown evidence category: {case.category}")
    evaluator = QualityGateEvaluator()
    baseline_output = evaluator.evaluate(baseline)
    mutated_output = evaluator.evaluate(mutated)
    _require(all(output.execution_readiness is ExecutionReadiness.PLANNING_ONLY for output in (baseline_output, mutated_output)), "evaluation must remain PLANNING_ONLY")
    if case.equal:
        _require(baseline.batch_fingerprint == mutated.batch_fingerprint, "fingerprints must normalize equally")
    else:
        _require(baseline.batch_fingerprint != mutated.batch_fingerprint, "fingerprints must differ")
    return baseline, mutated, actual_paths, _mutation_signature(case, baseline, mutated, actual_paths)


def validate_evidence_catalog(
    cases,
    *,
    required_leaves=frozenset(),
    required_identities=frozenset(),
    required_membership=frozenset(),
    required_order=frozenset(),
    structural_coverage=None,
):
    case_ids = tuple(case.case_id for case in cases)
    _require(len(case_ids) == len(set(case_ids)), "case IDs must be unique")
    validated = [(case, validate_fingerprint_case(case)) for case in cases]
    signatures = tuple(result[3] for _, result in validated)
    _require(len(signatures) == len(set(signatures)), "actual mutation signatures must be unique")
    _require(required_leaves <= {case.source for case in cases if case.category in ("leaf", "identity", "coherence")}, "normative leaf coverage is incomplete")
    _require(required_identities == {case.source for case in cases if case.category == "identity"}, "identity coverage is incomplete")
    _require(required_membership == {case.source for case in cases if case.category == "membership"}, "membership coverage is incomplete")
    _require(required_order == {case.source for case in cases if case.category == "order"}, "ordering coverage is incomplete")
    actual_leaf_paths = {}
    for case, (_, _, paths, _) in validated:
        if case.category == "leaf":
            for path in paths:
                actual_leaf_paths.setdefault(path, []).append(case.case_id)
    for node, descendants in (structural_coverage or {}).items():
        _require(descendants, f"structural node has no descendants: {node}")
        for descendant in descendants:
            _require(descendant in actual_leaf_paths, f"structural descendant lacks an actual leaf mutation: {descendant}")
            _require(len(actual_leaf_paths[descendant]) == 1, f"structural descendant is counted by multiple leaf cases: {descendant}")
    sources = {case.source for case in cases}
    _require("batch.batch_fingerprint" not in sources and "propagated_claim_contexts" not in sources, "derived fields must remain excluded")
    return validated


@pytest.mark.parametrize("case", ALL_CASES, ids=lambda case: case.case_id)
def test_declared_fingerprint_case_is_evaluator_valid(case):
    validate_fingerprint_case(case)


def test_fingerprint_coverage_manifest_is_independent_complete_and_unique():
    validated = validate_evidence_catalog(
        ALL_CASES,
        required_leaves=CALLER_FINGERPRINT_LEAVES,
        required_identities=REFERENCE_IDENTITIES,
        required_membership=COLLECTION_MEMBERSHIP,
        required_order=COLLECTION_ORDER,
        structural_coverage=STRUCTURAL_COVERAGE,
    )
    assert len(validated) == 67


def test_catalog_rejects_a_mislabelled_leaf_mutation():
    case = _leaf(
        "mislabelled", "claim.confidence", "batch.evaluation_at",
        lambda: batch(evaluation_at=UTC), lambda value: replace(value, evaluation_at=UTC + timedelta(seconds=1)),
    )
    with pytest.raises(EvidenceCatalogError, match="source label"):
        validate_evidence_catalog((case,), required_leaves=frozenset({"claim.confidence"}))


def test_catalog_rejects_duplicate_actual_mutations_with_different_case_ids():
    first = _leaf(
        "duplicate-a", "batch.evaluation_at", "batch.evaluation_at",
        lambda: batch(evaluation_at=UTC), lambda value: replace(value, evaluation_at=UTC + timedelta(seconds=1)),
    )
    second = replace(first, case_id="duplicate-b")
    with pytest.raises(EvidenceCatalogError, match="signatures"):
        validate_evidence_catalog((first, second), required_leaves=frozenset({"batch.evaluation_at"}))


def test_catalog_rejects_identity_rename_disguised_as_membership():
    baseline = batch()
    mutated = _replace_first_result(baseline, result_id="res_other")
    case = FingerprintCase(
        "fake-membership", "batch.results", lambda: baseline, lambda: mutated,
        category="membership", expected_changed_paths=frozenset({"batch.results"}),
        membership=MembershipExpectation(
            "batch.results", "result_id", ("res_one",), ("res_other",),
            frozenset({"res_other"}), frozenset({"res_one"}),
        ),
    )
    with pytest.raises(EvidenceCatalogError, match="diff path"):
        validate_evidence_catalog((case,), required_membership=frozenset({"batch.results"}))


def test_catalog_rejects_structural_metadata_without_an_actual_leaf_mutation():
    case = SIDE_LEAF_CASES[0]
    structural = {
        "contradiction.left": frozenset({
            "batch.contradictions[0].left.claim_id",
            "batch.contradictions[0].left.evidence_id",
        }),
    }
    with pytest.raises(EvidenceCatalogError, match="lacks an actual leaf mutation"):
        validate_evidence_catalog(
            (case,), required_leaves=frozenset({case.source}), structural_coverage=structural,
        )


def _negative_order_case(
    case_id,
    baseline_values,
    mutated_values,
    *,
    baseline_extra=(),
    mutated_extra=(),
    supplied_from_witness=True,
    element_count=None,
):
    source = "result.failure_reasons"
    builder = lambda raw: batch(results=(_fail(reasons=raw.value(source)),))
    witness = OrderingWitness(
        source,
        RawOrderingInput(((source, tuple(baseline_values)), *baseline_extra)),
        RawOrderingInput(((source, tuple(mutated_values)), *mutated_extra)),
        builder,
    )
    if supplied_from_witness:
        baseline_factory = lambda witness=witness: witness.builder(witness.baseline_raw)
        mutated_factory = lambda witness=witness: witness.builder(witness.mutated_raw)
    else:
        baseline_factory = batch
        mutated_factory = batch
    return FingerprintCase(
        case_id, source, baseline_factory, mutated_factory,
        equal=True, category="order", ordering=witness, element_count=element_count,
    )


_A = FailureReason.AUTHORITY_VIOLATION
_B = FailureReason.MODULE_DECLARED_FAILURE
_C = FailureReason.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize(
    "case",
    (
        _negative_order_case("identical-raw", (_A, _B), (_A, _B)),
        _negative_order_case("one-element", (_A,), (_A,)),
        _negative_order_case("identical-elements", (_A, _A), (_A, _A)),
        _negative_order_case("not-reverse", (_A, _B, _C), (_B, _C, _A)),
        _negative_order_case("membership-changed", (_A, _B), (_B, _C)),
        _negative_order_case("unrelated-raw-change", (_A, _B), (_B, _A), baseline_extra=(("raw.context", "one"),), mutated_extra=(("raw.context", "two"),)),
        _negative_order_case("witness-unused", (_A, _B), (_B, _A), supplied_from_witness=False),
        _negative_order_case("fake-element-count", (_A, _B), (_A, _B), element_count=2),
    ),
    ids=lambda case: case.case_id,
)
def test_catalog_rejects_invalid_ordering_witnesses(case):
    with pytest.raises(EvidenceCatalogError):
        validate_evidence_catalog((case,), required_order=frozenset({case.source}))


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
