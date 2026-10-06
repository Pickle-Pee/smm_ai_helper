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


class ProviderContextProjection(_StrictContract):
    """Fixed provider slots; semantic keys cannot repeat in an array."""
    business_goal: Excerpt | None = None
    product: Excerpt | None = None
    target_or_target_hypothesis: Excerpt | None = None
    customer_job_or_need: Excerpt | None = None
    relevant_alternative: Excerpt | None = None
    product_truth: Excerpt | None = None
    existing_proof: Excerpt | None = None
    geography: Excerpt | None = None
    economics: Excerpt | None = None
    message: Excerpt | None = None
    tone: Excerpt | None = None

    def to_internal(self, text: str) -> NaturalLanguageContextProjection:
        # Validate the entire wire shape before tolerating individual grounding failures.
        provider = ProviderContextProjection.model_validate(self)
        supplied = {key: value for key, value in provider.model_dump().items() if value is not None}
        accepted = {key: value for key, value in supplied.items() if value in text}
        log.info("Copilot provider projection accepted_fields=%s rejected_fields=%s accepted_count=%s rejected_count=%s",
                 sorted(accepted), sorted(supplied.keys() - accepted.keys()), len(accepted), len(supplied) - len(accepted))
        projection = NaturalLanguageContextProjection(facts=tuple(
            BusinessFactCandidate(key=key, value=value)
            for key, value in accepted.items()
        ))
        return validate_projection(projection, text)


class ProviderInterpretedRequest(_StrictContract):
    """Ephemeral provider response, never a public API or persisted DTO."""
    intent: MarketingIntent
    projection: ProviderContextProjection


def validate_interpreted_request(interpreted: InterpretedRequest, text: str) -> InterpretedRequest:
    interpreted = InterpretedRequest.model_validate(interpreted)
    validate_projection(interpreted.projection, text)
    if any(ref not in text for ref in (*interpreted.intent.provided_urls, *interpreted.intent.source_references)):
        raise CopilotContractError("Intent references must be supplied in the request")
    return interpreted


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
