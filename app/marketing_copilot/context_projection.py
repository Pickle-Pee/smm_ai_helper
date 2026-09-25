"""Bounded, non-authoritative request excerpts and server-owned conversion."""
import logging
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from .contracts import CopilotContractError, MarketingIntent, _StrictContract, _nonblank
from .context_resolver import ContextEntry
from .http_context import entry

log = logging.getLogger(__name__)

BusinessFactKey = Literal[
    "business_goal", "product", "target_or_target_hypothesis", "customer_job_or_need",
    "relevant_alternative", "product_truth", "existing_proof", "geography", "economics",
    "message", "tone",
]
Excerpt = Annotated[str, StringConstraints(min_length=1, max_length=4000), AfterValidator(_nonblank)]


class BusinessFactCandidate(_StrictContract):
    key: BusinessFactKey
    value: Excerpt


class NaturalLanguageContextProjection(_StrictContract):
    facts: tuple[BusinessFactCandidate, ...] = Field(max_length=11)

    @model_validator(mode="after")
    def unique_keys(self):
        keys = [fact.key for fact in self.facts]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate projected business field")
        return self


class InterpretedRequest(_StrictContract):
    """Two data products from one provider call; neither carries authority."""
    intent: MarketingIntent
    projection: NaturalLanguageContextProjection


def validate_projection(projection: NaturalLanguageContextProjection, text: str) -> NaturalLanguageContextProjection:
    projection = NaturalLanguageContextProjection.model_validate(projection)
    if any(candidate.value not in text for candidate in projection.facts):
        raise CopilotContractError("Projected values must be literal request excerpts")
    return projection


def merge_projected_context(
    explicit: tuple[ContextEntry, ...], projection: NaturalLanguageContextProjection, text: str,
) -> tuple[ContextEntry, ...]:
    """Presence masks projection, even for empty or unauthorized explicit entries.

    Keep original entries intact so the resolver still rejects duplicate keys.
    No model-supplied object, metadata, relevance or source role crosses here.
    """
    projection = validate_projection(projection, text)
    keys = {item.semantic_key for item in explicit}
    projected = tuple(entry(candidate.key, candidate.value, layer="request.projection")
                      for candidate in projection.facts if candidate.key not in keys)
    log.info("Copilot context projection fields=%s count=%s",
             sorted(item.semantic_key for item in projected), len(projected))
    return (*explicit, *projected)
