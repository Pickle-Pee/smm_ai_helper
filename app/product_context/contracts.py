"""Bounded, immutable context acquisition contracts, independent of execution."""
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.marketing_orchestrator.quality_gates.contracts import EvidenceRecord, EvidenceSourceClass
from .errors import SourceOutcome

Text = Annotated[str, StringConstraints(min_length=1, max_length=800, strip_whitespace=True)]
Url = Annotated[str, StringConstraints(min_length=1, max_length=2048)]
Identity = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")]


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True,
                              revalidate_instances="always", hide_input_in_errors=True)


class KnowledgeKind(str, Enum):
    OBSERVATION = "OBSERVATION"
    INFERENCE = "INFERENCE"
    UNKNOWN = "UNKNOWN"


class TrustKind(str, Enum):
    SITE_CLAIM = "site_claim"
    CONFIRMED_BUSINESS_FACT = "confirmed_business_fact"


class SnapshotField(str, Enum):
    PRODUCT = "stated_product_service"
    AUDIENCE = "stated_audience"
    JOB = "stated_customer_problems_jobs"
    VALUE = "stated_value_propositions"
    FEATURES = "stated_features_capabilities"
    PROOF = "stated_proof"
    PRICING = "stated_pricing"
    GEOGRAPHY = "stated_geography"
    CTA = "cta_conversion_path"
    POSITIONING = "positioning_message_observations"


class OwnedSiteRequest(FrozenContract):
    """Caller asserts ownership/authorization, not the truth of published claims.

    URL security validation belongs to acquire so rejection is a typed outcome.
    """
    owned_site_url: Url


class ExtractedStatement(FrozenContract):
    """Model returns semantic categories and literal quotes, never technical IDs."""
    field: SnapshotField
    kind: KnowledgeKind
    text: Text
    excerpts: tuple[Text, ...] = Field(max_length=3)

    @model_validator(mode="after")
    def support_shape(self):
        if self.kind is KnowledgeKind.UNKNOWN:
            if self.excerpts:
                raise ValueError("Unknowns cannot claim evidence")
        elif not self.excerpts:
            raise ValueError("Observations and inferences require excerpts")
        if self.kind is KnowledgeKind.OBSERVATION and self.excerpts != (self.text,):
            raise ValueError("An observation must be exactly one literal quote")
        if self.field in {SnapshotField.PRICING, SnapshotField.GEOGRAPHY} and self.kind is KnowledgeKind.INFERENCE:
            raise ValueError("Pricing/geography cannot be inferred")
        return self


class Extraction(FrozenContract):
    statements: tuple[ExtractedStatement, ...] = Field(max_length=30)


class SourceExcerpt(FrozenContract):
    """Minimal envelope around the existing shared EvidenceRecord."""
    record: EvidenceRecord
    page_url: Url
    excerpt: Text

    @model_validator(mode="after")
    def first_party(self):
        if self.record.source_class is not EvidenceSourceClass.FIRST_PARTY:
            raise ValueError("Owned page excerpts must remain first-party published claims")
        return self


class SnapshotStatement(FrozenContract):
    statement_id: Identity
    field: SnapshotField
    kind: KnowledgeKind
    text: Text
    evidence_ids: tuple[Identity, ...] = Field(max_length=3)
    trust: Literal[TrustKind.SITE_CLAIM] = TrustKind.SITE_CLAIM


class OwnedProductSnapshot(FrozenContract):
    schema_version: Literal["owned_product_snapshot.v1"] = "owned_product_snapshot.v1"
    snapshot_id: Identity
    owned_site_url: Url
    canonical_url: Url
    page_title: Text | None
    page_title_evidence_id: Identity | None
    statements: tuple[SnapshotStatement, ...] = Field(max_length=30)
    evidence: tuple[SourceExcerpt, ...] = Field(max_length=91)
    unknowns: tuple[Text, ...] = Field(max_length=48)
    source_role: Literal["caller_declared_owned_site"] = "caller_declared_owned_site"
    trust: Literal[TrustKind.SITE_CLAIM] = TrustKind.SITE_CLAIM

    @model_validator(mode="after")
    def linked_evidence(self):
        local = {e.record.evidence_id: e for e in self.evidence}
        if len(local) != len(self.evidence) or any(e.page_url != self.canonical_url for e in self.evidence):
            raise ValueError("Duplicate or foreign owned-page evidence")
        if len({s.statement_id for s in self.statements}) != len(self.statements):
            raise ValueError("Duplicate statement identity")
        if (self.page_title is None) != (self.page_title_evidence_id is None):
            raise ValueError("Page title requires evidence")
        if self.page_title is not None and (self.page_title_evidence_id not in local or
                local[self.page_title_evidence_id].excerpt != self.page_title):
            raise ValueError("Unsupported page title")
        for statement in self.statements:
            if not set(statement.evidence_ids) <= local.keys():
                raise ValueError("Unknown evidence reference")
            quotes = tuple(local[e].excerpt for e in statement.evidence_ids)
            ExtractedStatement(field=statement.field, kind=statement.kind, text=statement.text, excerpts=quotes)
        return self


class AcquisitionResult(FrozenContract):
    source: OwnedSiteRequest
    outcome: SourceOutcome
    snapshot: OwnedProductSnapshot | None = None

    @model_validator(mode="after")
    def coherent(self):
        if (self.outcome is SourceOutcome.ACQUIRED) != (self.snapshot is not None):
            raise ValueError("Only successful acquisition has a snapshot")
        if self.snapshot and self.snapshot.owned_site_url != self.source.owned_site_url:
            raise ValueError("Snapshot does not belong to requested source")
        return self


class ConfirmedBusinessFact(FrozenContract):
    """Explicit caller attestation, separate from and never mutating the snapshot.

    The caller owns authenticating the confirmer and collecting actual confirmation.
    This is not independent verification, and acquisition never constructs it.
    """
    trust: Literal[TrustKind.CONFIRMED_BUSINESS_FACT] = TrustKind.CONFIRMED_BUSINESS_FACT
    snapshot_id: Identity
    statement_ids: tuple[Identity, ...] = Field(min_length=1, max_length=30)
    confirmed_by: Text
    confirmation_reference: Text
