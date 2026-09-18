"""Deterministic adapters; published claims never fill verified product_truth."""
from dataclasses import replace

from app.marketing_copilot.application_contracts import CopilotRequest
from app.marketing_copilot.context_resolver import ContextEntry
from app.marketing_orchestrator import AuthorizedContextFact, PlanningInputKey
from app.module_registry import ModuleId
from .contracts import (AcquisitionResult, ConfirmedBusinessFact, KnowledgeKind,
                        OwnedProductSnapshot, SnapshotField, TrustKind)
from .errors import ProductContextError
from .service import identity

SCENARIOS = frozenset({"strategy_builder_v1", "competitive_positioning_v1"})
MODULES = frozenset({ModuleId.POSITIONING, ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS,
                     ModuleId.MARKET_ANALYSIS})
SEMANTIC_KEYS = {
    SnapshotField.PRODUCT: "product",
    SnapshotField.AUDIENCE: "target_or_target_hypothesis",
    SnapshotField.JOB: "customer_job_or_need",
}


def project_snapshot(snapshot: OwnedProductSnapshot) -> tuple[ContextEntry, ...]:
    snapshot = OwnedProductSnapshot.model_validate(snapshot)
    entries = []
    local = {e.record.evidence_id: e for e in snapshot.evidence}
    for field in SnapshotField:
        observations = tuple(s for s in snapshot.statements
            if s.field is field and s.kind is KnowledgeKind.OBSERVATION)
        if not observations:
            continue
        key = SEMANTIC_KEYS.get(field, "owned_site_" + field.value)
        evidence_ids = tuple(sorted({e for s in observations for e in s.evidence_ids}))
        entries.append(ContextEntry(key, AuthorizedContextFact(
            fact_id=identity("owned_context", snapshot.snapshot_id, key), label=key,
            input_key=PlanningInputKey(key) if field in SEMANTIC_KEYS else None,
            value={"trust": TrustKind.SITE_CLAIM.value, "source_role": snapshot.source_role,
                   "snapshot_id": snapshot.snapshot_id,
                   "site_states": [s.text for s in observations],
                   "evidence": [local[e].model_dump(mode="json") for e in evidence_ids]},
            source="Owned-site published claim; not independently verified; " + snapshot.canonical_url,
            evidence=evidence_ids, confidence=0.5, module_relevance=MODULES,
            scenario_relevance=SCENARIOS,
        )))
    return tuple(entries)


def attach_acquisition(request: CopilotRequest, acquired: AcquisitionResult) -> CopilotRequest:
    """Explicit caller step before Copilot.execute; no fetch inside Copilot.

    Keep the result/snapshot with the caller for review and confirmation, including
    observations masked by explicit current facts. Failure carries no stale site
    context; other authorized layers may still recover required inputs.
    """
    acquired = AcquisitionResult.model_validate(acquired)
    if request.owned_site_url is not None and request.owned_site_url != acquired.source.owned_site_url:
        raise ProductContextError("Acquisition belongs to another declared owned site")
    return replace(request, owned_site_url=acquired.source.owned_site_url,
                   owned_site_context=project_snapshot(acquired.snapshot) if acquired.snapshot else ())


def project_confirmation(snapshot: OwnedProductSnapshot, confirmation: ConfirmedBusinessFact) -> ContextEntry:
    """Caller-confirmed observations can explicitly enter CURRENT_REQUEST product_truth."""
    snapshot = OwnedProductSnapshot.model_validate(snapshot)
    confirmation = ConfirmedBusinessFact.model_validate(confirmation)
    if confirmation.snapshot_id != snapshot.snapshot_id:
        raise ProductContextError("Confirmation belongs to another snapshot")
    selected = {s.statement_id: s for s in snapshot.statements}
    ids = confirmation.statement_ids
    if len(set(ids)) != len(ids) or any(i not in selected or selected[i].kind is not KnowledgeKind.OBSERVATION for i in ids):
        raise ProductContextError("Only existing observations may be explicitly confirmed")
    statements = tuple(selected[i] for i in ids)
    return ContextEntry("product_truth", AuthorizedContextFact(
        fact_id=identity("confirmed", snapshot.snapshot_id, confirmation.model_dump(mode="json")),
        label="product_truth", input_key=PlanningInputKey.PRODUCT_TRUTH,
        value={"trust": TrustKind.CONFIRMED_BUSINESS_FACT.value,
               "confirmed_statements": [s.text for s in statements],
               "snapshot_id": snapshot.snapshot_id,
               "confirmed_by": confirmation.confirmed_by,
               "confirmation_reference": confirmation.confirmation_reference},
        source="Explicit caller confirmation; " + confirmation.confirmation_reference,
        evidence=tuple(sorted({e for s in statements for e in s.evidence_ids})),
        confidence=0.7, module_relevance=MODULES, scenario_relevance=SCENARIOS,
    ))
