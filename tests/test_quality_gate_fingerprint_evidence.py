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


class OrderingTarget(str, Enum):
    RESULTS = "RESULTS"
    CLAIMS = "CLAIMS"
    EVIDENCE = "EVIDENCE"
    ASSUMPTIONS = "ASSUMPTIONS"
    LIMITATIONS = "LIMITATIONS"
    CONTRADICTIONS = "CONTRADICTIONS"
    FAILURE_REASONS = "FAILURE_REASONS"
    BLOCKING_REASONS = "BLOCKING_REASONS"
    HANDOFF_MODULE_IDS = "HANDOFF_MODULE_IDS"
    PARENT_CLAIM_IDS = "PARENT_CLAIM_IDS"
    EVIDENCE_IDS = "EVIDENCE_IDS"
    ASSUMPTION_IDS = "ASSUMPTION_IDS"
    LIMITATION_IDS = "LIMITATION_IDS"
    CONTRADICTION_SIDES = "CONTRADICTION_SIDES"


class OrderingSemantics(str, Enum):
    NORMALIZED = "NORMALIZED"
    POSITIONAL = "POSITIONAL"


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
    baseline_raw: RawOrderingInput
    mutated_raw: RawOrderingInput


@dataclass(frozen=True)
class OrderingBatchFactory:
    target: OrderingTarget | object
    raw: RawOrderingInput


@dataclass(frozen=True)
class OrderingAdapter:
    target: OrderingTarget
    semantic_path: str
    raw_input_path: str
    builder: Callable[[RawOrderingInput], EvaluationBatch]
    projection: Callable[[EvaluationBatch], tuple[object, ...]]
    element_identity: Callable[[object], str]
    semantics: OrderingSemantics
    fingerprint_equal: bool


@dataclass(frozen=True)
class FingerprintCase:
    case_id: str
    declared_source: str | None
    baseline: BatchFactory | OrderingBatchFactory
    mutated: BatchFactory | OrderingBatchFactory
    category: str = "leaf"
    expected_changed_paths: frozenset[str] = frozenset()
    membership: MembershipExpectation | None = None
    ordering: OrderingWitness | None = None
    ordering_target: OrderingTarget | object | None = None
    element_count: int | None = None

    @property
    def source(self):
        if self.ordering_target is None:
            return self.declared_source
        if type(self.ordering_target) is not OrderingTarget:
            raise EvidenceCatalogError("UNKNOWN_ORDERING_TARGET")
        return ORDERING_ADAPTER_BY_TARGET[self.ordering_target].semantic_path


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


def _ordering_adapters():
    result_a, result_b = _pass("res_a", "clm_a"), _pass("res_b", "clm_b")
    claims, claims_builder = _nested_order_builder("claims")
    evidence, evidence_builder = _nested_order_builder("evidence")
    assumptions, assumptions_builder = _nested_order_builder("assumptions")
    limitations, limitations_builder = _nested_order_builder("limitations")
    parent_ids, parent_builder = _id_order_builder("parent_claim_ids")
    evidence_ids, evidence_ids_builder = _id_order_builder("evidence_ids")
    assumption_ids, assumption_ids_builder = _id_order_builder("assumption_ids")
    limitation_ids, limitation_ids_builder = _id_order_builder("limitation_ids")
    contradictions = (
        ContradictionInput("ctr_a", _side("clm_a"), _side("clm_b")),
        ContradictionInput("ctr_b", _side("clm_a"), _side("clm_b")),
    )
    contradiction_base = _contradiction_batch()

    def adapter(target, path, builder, projection, identity, *, positional=False):
        return OrderingAdapter(
            target, path, path, builder, projection, identity,
            OrderingSemantics.POSITIONAL if positional else OrderingSemantics.NORMALIZED,
            not positional,
        )

    adapters = (
        adapter(
            OrderingTarget.RESULTS,
            "batch.results",
            lambda raw: EvaluationBatch("bat_order", raw.value("batch.results")),
            lambda value: value.results,
            lambda item: item.result_id,
        ),
        adapter(OrderingTarget.CLAIMS, "result.claims", claims_builder, lambda value: value.results[0].claims, lambda item: item.claim_id),
        adapter(OrderingTarget.EVIDENCE, "result.evidence", evidence_builder, lambda value: value.results[0].evidence, lambda item: item.evidence_id),
        adapter(OrderingTarget.ASSUMPTIONS, "result.assumptions", assumptions_builder, lambda value: value.results[0].assumptions, lambda item: item.assumption_id),
        adapter(OrderingTarget.LIMITATIONS, "result.limitations", limitations_builder, lambda value: value.results[0].limitations, lambda item: item.limitation_id),
        adapter(
            OrderingTarget.CONTRADICTIONS,
            "batch.contradictions",
            lambda raw: EvaluationBatch("bat_order", (result_a, result_b), raw.value("batch.contradictions")),
            lambda value: value.contradictions,
            lambda item: item.contradiction_id,
        ),
        adapter(
            OrderingTarget.FAILURE_REASONS,
            "result.failure_reasons",
            lambda raw: batch(results=(_fail(reasons=raw.value("result.failure_reasons")),)),
            lambda value: tuple(value.results[0].failure_reasons),
            lambda item: item.value,
        ),
        adapter(
            OrderingTarget.BLOCKING_REASONS,
            "result.blocking_reasons",
            lambda raw: batch(results=(_blocked(reasons=raw.value("result.blocking_reasons")),)),
            lambda value: tuple(value.results[0].blocking_reasons),
            lambda item: item.value,
        ),
        adapter(
            OrderingTarget.HANDOFF_MODULE_IDS,
            "result.handoff_module_ids",
            lambda raw: batch(results=(_pass(handoff_module_ids=raw.value("result.handoff_module_ids")),)),
            lambda value: tuple(value.results[0].handoff_module_ids),
            lambda item: item.value,
        ),
        adapter(OrderingTarget.PARENT_CLAIM_IDS, "claim.parent_claim_ids", parent_builder, lambda value: value.results[0].claims[2].parent_claim_ids, lambda item: item),
        adapter(OrderingTarget.EVIDENCE_IDS, "claim.evidence_ids", evidence_ids_builder, lambda value: value.results[0].claims[2].evidence_ids, lambda item: item),
        adapter(OrderingTarget.ASSUMPTION_IDS, "claim.assumption_ids", assumption_ids_builder, lambda value: value.results[0].claims[2].assumption_ids, lambda item: item),
        adapter(OrderingTarget.LIMITATION_IDS, "claim.limitation_ids", limitation_ids_builder, lambda value: value.results[0].claims[2].limitation_ids, lambda item: item),
        adapter(
            OrderingTarget.CONTRADICTION_SIDES,
            "contradiction.left/right",
            lambda raw: replace(
                contradiction_base,
                contradictions=(
                    replace(
                        contradiction_base.contradictions[0],
                        left=raw.value("contradiction.left/right")[0],
                        right=raw.value("contradiction.left/right")[1],
                    ),
                ),
            ),
            lambda value: (value.contradictions[0].left, value.contradictions[0].right),
            lambda item: _stable_text(item),
            positional=True,
        ),
    )
    values = {
        OrderingTarget.RESULTS: (result_a, result_b),
        OrderingTarget.CLAIMS: claims,
        OrderingTarget.EVIDENCE: evidence,
        OrderingTarget.ASSUMPTIONS: assumptions,
        OrderingTarget.LIMITATIONS: limitations,
        OrderingTarget.CONTRADICTIONS: contradictions,
        OrderingTarget.FAILURE_REASONS: (FailureReason.AUTHORITY_VIOLATION, FailureReason.MODULE_DECLARED_FAILURE),
        OrderingTarget.BLOCKING_REASONS: (BlockingReason.MISSING_CAPABILITY, BlockingReason.TOOL_UNAVAILABLE),
        OrderingTarget.HANDOFF_MODULE_IDS: (ModuleId.POSITIONING, ModuleId.EXPERIMENTS),
        OrderingTarget.PARENT_CLAIM_IDS: parent_ids,
        OrderingTarget.EVIDENCE_IDS: evidence_ids,
        OrderingTarget.ASSUMPTION_IDS: assumption_ids,
        OrderingTarget.LIMITATION_IDS: limitation_ids,
        OrderingTarget.CONTRADICTION_SIDES: (contradiction_base.contradictions[0].left, contradiction_base.contradictions[0].right),
    }
    return adapters, values


ORDERING_ADAPTERS, ORDERING_VALUES = _ordering_adapters()
ORDERING_ADAPTER_BY_TARGET = {adapter.target: adapter for adapter in ORDERING_ADAPTERS}


def _ordering_case(case_id, target, values=None, *, extra_fields=()):
    adapter = ORDERING_ADAPTER_BY_TARGET[target]
    values = tuple(values if values is not None else ORDERING_VALUES[target])
    baseline_raw = RawOrderingInput(((adapter.raw_input_path, values), *extra_fields))
    mutated_raw = RawOrderingInput(((adapter.raw_input_path, tuple(reversed(values))), *extra_fields))
    witness = OrderingWitness(baseline_raw, mutated_raw)
    return FingerprintCase(
        case_id,
        None,
        OrderingBatchFactory(target, baseline_raw),
        OrderingBatchFactory(target, mutated_raw),
        category="order",
        ordering=witness,
        ordering_target=target,
    )


def _order_cases():
    return tuple(
        _ordering_case(case_id, target)
        for case_id, target in (
            ("results-order", OrderingTarget.RESULTS),
            ("claims-order", OrderingTarget.CLAIMS),
            ("evidence-order", OrderingTarget.EVIDENCE),
            ("assumptions-order", OrderingTarget.ASSUMPTIONS),
            ("limitations-order", OrderingTarget.LIMITATIONS),
            ("contradictions-order", OrderingTarget.CONTRADICTIONS),
            ("failure-reasons-order", OrderingTarget.FAILURE_REASONS),
            ("blocking-reasons-order", OrderingTarget.BLOCKING_REASONS),
            ("handoffs-order", OrderingTarget.HANDOFF_MODULE_IDS),
            ("parent_claim_ids-order", OrderingTarget.PARENT_CLAIM_IDS),
            ("evidence_ids-order", OrderingTarget.EVIDENCE_IDS),
            ("assumption_ids-order", OrderingTarget.ASSUMPTION_IDS),
            ("limitation_ids-order", OrderingTarget.LIMITATION_IDS),
            ("contradiction-side-position", OrderingTarget.CONTRADICTION_SIDES),
        )
    )


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
    _require(len(values) == len(raw.fields), "ORDERING_UNRELATED_RAW_CHANGE")
    return values


def _validate_ordering_adapter_registry(adapters):
    _require(type(adapters) is tuple and adapters, "INVALID_ORDERING_ADAPTER_REGISTRY")
    for adapter in adapters:
        _require(type(adapter) is OrderingAdapter, "INVALID_ORDERING_ADAPTER_REGISTRY")
        _require(type(adapter.target) is OrderingTarget, "INVALID_ORDERING_ADAPTER_REGISTRY")
        _require(type(adapter.semantic_path) is str and adapter.semantic_path, "INVALID_ORDERING_ADAPTER_REGISTRY")
        _require(type(adapter.raw_input_path) is str and adapter.raw_input_path, "INVALID_ORDERING_ADAPTER_REGISTRY")
        _require(callable(adapter.builder) and callable(adapter.projection) and callable(adapter.element_identity), "INVALID_ORDERING_ADAPTER_REGISTRY")
        _require(type(adapter.semantics) is OrderingSemantics, "INVALID_ORDERING_ADAPTER_REGISTRY")
        _require(type(adapter.fingerprint_equal) is bool, "INVALID_ORDERING_ADAPTER_REGISTRY")
    targets = tuple(adapter.target for adapter in adapters)
    semantic_paths = tuple(adapter.semantic_path for adapter in adapters)
    raw_paths = tuple(adapter.raw_input_path for adapter in adapters)
    _require(len(targets) == len(set(targets)), "DUPLICATE_ORDERING_TARGET")
    _require(len(semantic_paths) == len(set(semantic_paths)), "DUPLICATE_ORDERING_SEMANTIC_PATH")
    _require(len(raw_paths) == len(set(raw_paths)), "DUPLICATE_ORDERING_RAW_PATH")
    return {adapter.target: adapter for adapter in adapters}


def _resolve_ordering_adapter(case, adapter_by_target):
    target = case.ordering_target
    if type(target) is not OrderingTarget:
        aliases = {
            *(item.value for item in OrderingTarget),
            *(adapter.semantic_path for adapter in adapter_by_target.values()),
            *(adapter.raw_input_path for adapter in adapter_by_target.values()),
        }
        code = "ORDERING_TARGET_ALIAS" if type(target) is str and target in aliases else "UNKNOWN_ORDERING_TARGET"
        raise EvidenceCatalogError(code)
    _require(target in adapter_by_target, "UNKNOWN_ORDERING_TARGET")
    _require(case.declared_source is None, "ORDERING_ADAPTER_MISMATCH")
    return adapter_by_target[target]


def _ordered_adapter_values(adapter, values):
    values = tuple(values)
    if adapter.semantics is OrderingSemantics.NORMALIZED:
        values = tuple(sorted(values, key=adapter.element_identity))
    return tuple(_stable_text(item) for item in values)


def _validate_ordering_witness(case, adapter_by_target):
    adapter = _resolve_ordering_adapter(case, adapter_by_target)
    witness = case.ordering
    _require(type(witness) is OrderingWitness, "ORDERING_WITNESS_NOT_USED")
    _require(
        type(case.baseline) is OrderingBatchFactory
        and type(case.mutated) is OrderingBatchFactory
        and case.baseline.target is adapter.target
        and case.mutated.target is adapter.target
        and _stable_text(case.baseline.raw) == _stable_text(witness.baseline_raw)
        and _stable_text(case.mutated.raw) == _stable_text(witness.mutated_raw),
        "ORDERING_WITNESS_NOT_USED",
    )
    _require(case.element_count in (None, 0), "LEGACY_ELEMENT_COUNT_FORBIDDEN")
    before_fields = _raw_fields(witness.baseline_raw)
    after_fields = _raw_fields(witness.mutated_raw)
    _require(adapter.raw_input_path in before_fields and adapter.raw_input_path in after_fields, "ORDERING_ADAPTER_MISMATCH")
    before = before_fields[adapter.raw_input_path]
    after = after_fields[adapter.raw_input_path]
    _require(type(before) is tuple and type(after) is tuple, "ORDERING_ADAPTER_MISMATCH")
    _require(len(before) >= 2 and len(after) >= 2, "ORDERING_TOO_SHORT")
    before_keys = tuple(_stable_text(item) for item in before)
    after_keys = tuple(_stable_text(item) for item in after)
    _require(len(set(before_keys)) >= 2 and len(set(after_keys)) >= 2, "ORDERING_ELEMENTS_NOT_DISTINCT")
    _require(Counter(before_keys) == Counter(after_keys), "ORDERING_MEMBERSHIP_CHANGED")
    _require(before_keys != after_keys, "ORDERING_NO_CHANGE")
    _require(after_keys == tuple(reversed(before_keys)), "ORDERING_NOT_EXACT_REVERSE")
    _require(set(before_fields) == set(after_fields), "ORDERING_UNRELATED_RAW_CHANGE")
    raw_diffs = {name for name in before_fields if _stable_text(before_fields[name]) != _stable_text(after_fields[name])}
    _require(raw_diffs == {adapter.raw_input_path}, "ORDERING_UNRELATED_RAW_CHANGE")
    built_before = adapter.builder(witness.baseline_raw)
    built_after = adapter.builder(witness.mutated_raw)
    projected_before = adapter.projection(built_before)
    projected_after = adapter.projection(built_after)
    _require(type(projected_before) is tuple and type(projected_after) is tuple, "ORDERING_ADAPTER_MISMATCH")
    _require(_ordered_adapter_values(adapter, before) == _ordered_adapter_values(adapter, projected_before), "ORDERING_ADAPTER_MISMATCH")
    _require(_ordered_adapter_values(adapter, after) == _ordered_adapter_values(adapter, projected_after), "ORDERING_ADAPTER_MISMATCH")
    if adapter.semantics is OrderingSemantics.POSITIONAL:
        _require(built_before != built_after, "ORDERING_ADAPTER_MISMATCH")
    return built_before, built_after, adapter


def _validate_membership(case, baseline, mutated, actual_paths):
    expected = case.membership
    _require(expected is not None, "membership evidence requires a declaration")
    _require(actual_paths == set(case.expected_changed_paths) == {expected.path}, "MEMBERSHIP_PATH_MISMATCH")
    _require(_logical_path(expected.path) == case.source, "MEMBERSHIP_PATH_MISMATCH")
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


def _unordered_stable_pair(left, right):
    endpoints = (_stable_text(left), _stable_text(right))
    return tuple(sorted(endpoints, key=lambda item: item.encode("utf-8")))


def _mutation_signature(case, baseline, mutated, actual_paths, adapter=None):
    changed_values = [
        [path, _unordered_stable_pair(_get_path(baseline, path), _get_path(mutated, path))]
        for path in sorted(actual_paths)
    ]
    raw = None
    if adapter is not None:
        before = case.ordering.baseline_raw.value(adapter.raw_input_path)
        after = case.ordering.mutated_raw.value(adapter.raw_input_path)
        raw = [adapter.semantic_path, _unordered_stable_pair(before, after)]
    payload = [_unordered_stable_pair(baseline, mutated), sorted(actual_paths), changed_values, raw]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_fingerprint_case(case, *, adapter_by_target=None):
    adapter_by_target = adapter_by_target or _validate_ordering_adapter_registry(ORDERING_ADAPTERS)
    adapter = None
    if case.category == "order":
        baseline, mutated, adapter = _validate_ordering_witness(case, adapter_by_target)
    else:
        _require(case.ordering is None, "non-ordering evidence must not carry an ordering witness")
        _require(case.ordering_target is None, "non-ordering evidence must not carry an ordering target")
        _require(case.element_count in (None, 0), "legacy element_count metadata is forbidden")
        baseline = case.baseline()
        mutated = case.mutated()
        _require(baseline != mutated, f"{case.case_id} is a semantic no-op")
    actual_paths = _diff_paths(baseline, mutated)
    if case.category == "leaf":
        _require(actual_paths == set(case.expected_changed_paths) and len(actual_paths) == 1, "isolated leaf paths do not match their declaration")
        _require(_logical_path(next(iter(actual_paths))) == case.source, "LEAF_SOURCE_MISMATCH")
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
    fingerprint_equal = adapter.fingerprint_equal if adapter is not None else False
    if fingerprint_equal:
        _require(baseline.batch_fingerprint == mutated.batch_fingerprint, "fingerprints must normalize equally")
    else:
        _require(baseline.batch_fingerprint != mutated.batch_fingerprint, "fingerprints must differ")
    return baseline, mutated, actual_paths, _mutation_signature(case, baseline, mutated, actual_paths, adapter)


def validate_evidence_catalog(
    cases,
    *,
    required_leaves=frozenset(),
    required_identities=frozenset(),
    required_membership=frozenset(),
    required_order=frozenset(),
    structural_coverage=None,
    ordering_adapters=ORDERING_ADAPTERS,
):
    adapter_by_target = _validate_ordering_adapter_registry(ordering_adapters)
    case_ids = tuple(case.case_id for case in cases)
    _require(len(case_ids) == len(set(case_ids)), "case IDs must be unique")
    validated = [(case, validate_fingerprint_case(case, adapter_by_target=adapter_by_target)) for case in cases]
    signatures = tuple(result[3] for _, result in validated)
    _require(len(signatures) == len(set(signatures)), "DUPLICATE_MUTATION_SIGNATURE")
    _require(required_leaves <= {case.source for case in cases if case.category in ("leaf", "identity", "coherence")}, "normative leaf coverage is incomplete")
    _require(required_identities == {case.source for case in cases if case.category == "identity"}, "identity coverage is incomplete")
    _require(required_membership == {case.source for case in cases if case.category == "membership"}, "membership coverage is incomplete")
    ordering_sources = {
        _resolve_ordering_adapter(case, adapter_by_target).semantic_path
        for case in cases
        if case.category == "order"
    }
    _require(required_order == ordering_sources, "ordering coverage is incomplete")
    actual_leaf_paths = {}
    for case, (_, _, paths, _) in validated:
        if case.category == "leaf":
            for path in paths:
                actual_leaf_paths.setdefault(path, []).append(case.case_id)
    for node, descendants in (structural_coverage or {}).items():
        _require(descendants, f"structural node has no descendants: {node}")
        for descendant in descendants:
            _require(descendant in actual_leaf_paths, "MISSING_STRUCTURAL_DESCENDANT")
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
    with pytest.raises(EvidenceCatalogError, match="^LEAF_SOURCE_MISMATCH$"):
        validate_evidence_catalog((case,), required_leaves=frozenset({"claim.confidence"}))


def test_catalog_rejects_duplicate_actual_mutations_with_different_case_ids():
    first = _leaf(
        "duplicate-a", "batch.evaluation_at", "batch.evaluation_at",
        lambda: batch(evaluation_at=UTC), lambda value: replace(value, evaluation_at=UTC + timedelta(seconds=1)),
    )
    second = replace(first, case_id="duplicate-b")
    with pytest.raises(EvidenceCatalogError, match="^DUPLICATE_MUTATION_SIGNATURE$"):
        validate_evidence_catalog((first, second), required_leaves=frozenset({"batch.evaluation_at"}))


def _evaluation_at_case(case_id, before, after):
    return _leaf(
        case_id,
        "batch.evaluation_at",
        "batch.evaluation_at",
        lambda before=before: batch(evaluation_at=before),
        lambda value, after=after: replace(value, evaluation_at=after),
    )


def test_catalog_rejects_the_same_leaf_mutation_in_reverse():
    first = _evaluation_at_case("reverse-leaf-a", UTC, UTC + timedelta(seconds=1))
    reversed_case = _evaluation_at_case("reverse-leaf-b", UTC + timedelta(seconds=1), UTC)
    with pytest.raises(EvidenceCatalogError, match="^DUPLICATE_MUTATION_SIGNATURE$"):
        validate_evidence_catalog((first, reversed_case), required_leaves=frozenset({"batch.evaluation_at"}))


def test_catalog_rejects_independently_rebuilt_reverse_endpoints():
    first = _evaluation_at_case("rebuilt-reverse-a", UTC, UTC + timedelta(seconds=1))
    rebuilt = FingerprintCase(
        "rebuilt-reverse-b",
        "batch.evaluation_at",
        lambda: EvaluationBatch("bat_one", (_pass(),), evaluation_at=UTC + timedelta(seconds=1)),
        lambda: EvaluationBatch("bat_one", (_pass(),), evaluation_at=UTC),
        expected_changed_paths=frozenset({"batch.evaluation_at"}),
    )
    with pytest.raises(EvidenceCatalogError, match="^DUPLICATE_MUTATION_SIGNATURE$"):
        validate_evidence_catalog((first, rebuilt), required_leaves=frozenset({"batch.evaluation_at"}))


def test_catalog_keeps_genuinely_different_mutations_distinct():
    first = _evaluation_at_case("distinct-a", UTC, UTC + timedelta(seconds=1))
    second = _evaluation_at_case("distinct-b", UTC, UTC + timedelta(seconds=2))
    validated = validate_evidence_catalog((first, second), required_leaves=frozenset({"batch.evaluation_at"}))
    assert len({result[3] for _, result in validated}) == 2


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
    with pytest.raises(EvidenceCatalogError, match="^MEMBERSHIP_PATH_MISMATCH$"):
        validate_evidence_catalog((case,), required_membership=frozenset({"batch.results"}))


def test_catalog_rejects_the_same_membership_mutation_in_reverse():
    forward = MEMBERSHIP_CASES[0]
    expected = forward.membership
    reversed_case = replace(
        forward,
        case_id="results-membership-reversed",
        baseline=forward.mutated,
        mutated=forward.baseline,
        membership=replace(
            expected,
            baseline_ids=expected.mutated_ids,
            mutated_ids=expected.baseline_ids,
            added_ids=expected.removed_ids,
            removed_ids=expected.added_ids,
        ),
    )
    with pytest.raises(EvidenceCatalogError, match="^DUPLICATE_MUTATION_SIGNATURE$"):
        validate_evidence_catalog((forward, reversed_case), required_membership=frozenset({"batch.results"}))


def test_catalog_rejects_the_same_identity_closure_in_reverse():
    forward = IDENTITY_CASES[0]
    reversed_case = replace(forward, case_id="batch-id-reversed", baseline=forward.mutated, mutated=forward.baseline)
    with pytest.raises(EvidenceCatalogError, match="^DUPLICATE_MUTATION_SIGNATURE$"):
        validate_evidence_catalog((forward, reversed_case), required_identities=frozenset({"batch.batch_id"}))


def test_catalog_rejects_structural_metadata_without_an_actual_leaf_mutation():
    case = SIDE_LEAF_CASES[0]
    structural = {
        "contradiction.left": frozenset({
            "batch.contradictions[0].left.claim_id",
            "batch.contradictions[0].left.evidence_id",
        }),
    }
    with pytest.raises(EvidenceCatalogError, match="^MISSING_STRUCTURAL_DESCENDANT$"):
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
    target = OrderingTarget.FAILURE_REASONS
    adapter = ORDERING_ADAPTER_BY_TARGET[target]
    witness = OrderingWitness(
        RawOrderingInput(((adapter.raw_input_path, tuple(baseline_values)), *baseline_extra)),
        RawOrderingInput(((adapter.raw_input_path, tuple(mutated_values)), *mutated_extra)),
    )
    if supplied_from_witness:
        baseline_factory = OrderingBatchFactory(target, witness.baseline_raw)
        mutated_factory = OrderingBatchFactory(target, witness.mutated_raw)
    else:
        baseline_factory = batch
        mutated_factory = batch
    return FingerprintCase(
        case_id,
        None,
        baseline_factory,
        mutated_factory,
        category="order",
        ordering=witness,
        ordering_target=target,
        element_count=element_count,
    )


_A = FailureReason.AUTHORITY_VIOLATION
_B = FailureReason.MODULE_DECLARED_FAILURE
_C = FailureReason.INSUFFICIENT_EVIDENCE


def _validate_single_order_case(case, *, adapters=ORDERING_ADAPTERS, source="result.failure_reasons"):
    return validate_evidence_catalog((case,), required_order=frozenset({source}), ordering_adapters=adapters)


def test_catalog_rejects_an_unknown_ordering_target():
    case = replace(_negative_order_case("unknown-target", (_A, _B), (_B, _A)), ordering_target="NOT_A_TARGET")
    with pytest.raises(EvidenceCatalogError, match="^UNKNOWN_ORDERING_TARGET$"):
        _validate_single_order_case(case)


def test_catalog_rejects_a_semantic_ordering_alias():
    case = replace(_negative_order_case("semantic-alias", (_A, _B), (_B, _A)), ordering_target="result.failure_reasons")
    with pytest.raises(EvidenceCatalogError, match="^ORDERING_TARGET_ALIAS$"):
        _validate_single_order_case(case)


def test_catalog_rejects_a_forged_source_for_a_fixed_adapter():
    case = replace(_negative_order_case("forged-source", (_A, _B), (_B, _A)), declared_source="claim.confidence")
    with pytest.raises(EvidenceCatalogError, match="^ORDERING_ADAPTER_MISMATCH$"):
        _validate_single_order_case(case)


def test_catalog_rejects_an_ordering_adapter_field_mismatch():
    case = _negative_order_case("adapter-field-mismatch", (_A, _B), (_B, _A))
    valid = ORDERING_ADAPTER_BY_TARGET[OrderingTarget.FAILURE_REASONS]
    mismatched = replace(
        valid,
        semantic_path="result.module_status",
        projection=lambda value: (value.results[0].module_status,),
    )
    with pytest.raises(EvidenceCatalogError, match="^ORDERING_ADAPTER_MISMATCH$"):
        _validate_single_order_case(case, adapters=(mismatched,), source="result.module_status")


def test_catalog_rejects_identical_raw_sequences_at_the_no_change_guard():
    case = _negative_order_case("identical-raw", (_A, _B, _A), (_A, _B, _A))
    with pytest.raises(EvidenceCatalogError, match="^ORDERING_NO_CHANGE$"):
        _validate_single_order_case(case)


def test_catalog_rejects_a_one_element_sequence_at_the_length_guard():
    case = _negative_order_case("one-element", (_A,), (_A,))
    with pytest.raises(EvidenceCatalogError, match="^ORDERING_TOO_SHORT$"):
        _validate_single_order_case(case)


def test_catalog_rejects_two_identical_elements_at_the_distinctness_guard():
    case = _negative_order_case("identical-elements", (_A, _A), (_A, _A))
    with pytest.raises(EvidenceCatalogError, match="^ORDERING_ELEMENTS_NOT_DISTINCT$"):
        _validate_single_order_case(case)


def test_catalog_rejects_a_non_reversal_permutation_at_the_reversal_guard():
    case = _negative_order_case("not-reverse", (_A, _B, _C), (_B, _C, _A))
    with pytest.raises(EvidenceCatalogError, match="^ORDERING_NOT_EXACT_REVERSE$"):
        _validate_single_order_case(case)


def test_catalog_rejects_changed_membership_at_the_multiset_guard():
    case = _negative_order_case("membership-changed", (_A, _B), (_B, _C))
    with pytest.raises(EvidenceCatalogError, match="^ORDERING_MEMBERSHIP_CHANGED$"):
        _validate_single_order_case(case)


def test_catalog_rejects_an_unrelated_raw_field_change_at_its_guard():
    case = _negative_order_case(
        "unrelated-raw-change",
        (_A, _B),
        (_B, _A),
        baseline_extra=(("raw.context", "one"),),
        mutated_extra=(("raw.context", "two"),),
    )
    with pytest.raises(EvidenceCatalogError, match="^ORDERING_UNRELATED_RAW_CHANGE$"):
        _validate_single_order_case(case)


def test_catalog_rejects_a_witness_not_used_to_build_contracts():
    case = _negative_order_case("witness-unused", (_A, _B), (_B, _A), supplied_from_witness=False)
    with pytest.raises(EvidenceCatalogError, match="^ORDERING_WITNESS_NOT_USED$"):
        _validate_single_order_case(case)


def test_catalog_rejects_legacy_element_count_without_a_noop_fixture():
    case = _negative_order_case("fake-element-count", (_A, _B), (_B, _A), element_count=2)
    with pytest.raises(EvidenceCatalogError, match="^LEGACY_ELEMENT_COUNT_FORBIDDEN$"):
        _validate_single_order_case(case)


def test_catalog_rejects_duplicate_semantic_adapter_registration():
    first = ORDERING_ADAPTER_BY_TARGET[OrderingTarget.FAILURE_REASONS]
    duplicate = replace(
        first,
        target=OrderingTarget.BLOCKING_REASONS,
        raw_input_path="duplicate.failure_reasons",
    )
    with pytest.raises(EvidenceCatalogError, match="^DUPLICATE_ORDERING_SEMANTIC_PATH$"):
        validate_evidence_catalog((), ordering_adapters=(first, duplicate))


def test_catalog_rejects_the_same_ordering_witness_in_reverse():
    forward = _ordering_case("ordering-forward", OrderingTarget.FAILURE_REASONS)
    witness = forward.ordering
    reversed_case = replace(
        forward,
        case_id="ordering-reversed",
        baseline=OrderingBatchFactory(forward.ordering_target, witness.mutated_raw),
        mutated=OrderingBatchFactory(forward.ordering_target, witness.baseline_raw),
        ordering=OrderingWitness(witness.mutated_raw, witness.baseline_raw),
    )
    with pytest.raises(EvidenceCatalogError, match="^DUPLICATE_MUTATION_SIGNATURE$"):
        validate_evidence_catalog((forward, reversed_case), required_order=frozenset({"result.failure_reasons"}))


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
