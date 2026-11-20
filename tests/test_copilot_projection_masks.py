"""Ungrounded request projection slots mask lower-layer context (production regression).

Telegram acceptance graph 2ad59a05… (a602f4e): the provider projected the request's
product as a nominative paraphrase («курс фотографии …») of the message text
(«курса фотографии …»). Literal grounding correctly dropped it, but the resolver then
filled `product` from the account BrandProfile and a published POSITIONING statement
named an unrelated product. A slot the request itself supplied must never be filled
from BrandProfile, project or conversation context.
"""
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.marketing_copilot.api_contracts import ExecuteRequest
from app.marketing_copilot.application_contracts import CopilotRequest, ResultKind
from app.marketing_copilot.context_projection import (
    BusinessFactCandidate, InterpretedRequest, NaturalLanguageContextProjection, ProviderContextProjection,
    merge_projected_context,
)
from app.marketing_copilot.context_resolver import ContextEntry, ContextResolver
from app.marketing_orchestrator import AuthorizedContextFact, PlanningInputKey
from app.module_registry import ModuleId
from app.marketing_copilot.contracts import CopilotContractError, IntentKind
from app.marketing_copilot.factory import build_marketing_copilot_service
from app.marketing_copilot.http_context import brand_entries, current_entries, entry
from app.marketing_copilot.interpretation_store import validate_interpretation
from tests.test_copilot_application import intent_model
from tests.test_marketing_copilot import intent
from tests.test_module_executors import FakeModel

MESSAGE = (
    "Разработай маркетинговую стратегию для курса фотографии «KADRTEST». "
    "Аудитория — взрослые, которые знакомятся с фотографией. "
    "Цель — проверить интерес к предложению и причины обращения. "
    "Подтверждённые сведения владельца: участники выполняют практические задания и получают письменную "
    "обратную связь; для занятий не требуется профессиональное оборудование. "
    "Есть демонстрационный образец, который показывает сравнение снимков. "
    "Покажи позиционирование, стратегические приоритеты и эксперименты для проверки гипотез."
)
GROUNDED = {
    "business_goal": "Цель — проверить интерес к предложению и причины обращения.",
    "target_or_target_hypothesis": "Аудитория — взрослые, которые знакомятся с фотографией.",
    "product_truth": ("участники выполняют практические задания и получают письменную обратную связь; "
                      "для занятий не требуется профессиональное оборудование."),
    "existing_proof": "Есть демонстрационный образец, который показывает сравнение снимков.",
    "message": "Покажи позиционирование, стратегические приоритеты и эксперименты для проверки гипотез.",
}
PARAPHRASED_PRODUCT = "курс фотографии «KADRTEST»"  # nominative; the message says «курса фотографии»
BRAND_PRODUCT = "Маркетинговый ТГ бот"


def strategy_service(facts):
    svc = build_marketing_copilot_service(intent_model=intent_model(IntentKind.MARKETING_STRATEGY, facts=facts),
                                          module_model=FakeModel(), registry_version="1.3.0")
    svc.graph_service = SimpleNamespace(start_compiled_run=AsyncMock())
    return svc


def execute(svc, *, message=MESSAGE, context=None, owned=(), brand=None):
    payload = ExecuteRequest(request_key="request-1", message=message, context=context or {})
    request = CopilotRequest(actor_id=1, request_id="request-1", message=message,
                             current_request=current_entries(payload), owned_site_context=owned,
                             owned_site_url="https://example.test" if owned else None,
                             brand_profile=brand_entries({"product": BRAND_PRODUCT} if brand is None else brand))
    return asyncio.run(svc.execute(request))


def started_product(svc):
    plan = svc.graph_service.start_compiled_run.call_args.kwargs["plan"]
    values = {(f.value if isinstance(f.value, str) else "<site_claim>", f.source.split(":", 1)[0]) for node in plan.nodes
              for f in (*node.context_packet.known_facts, *node.context_packet.relevant_project_context)
              if f.label == "product"}
    return values


def test_paraphrased_product_is_masked_not_dropped():
    assert PARAPHRASED_PRODUCT not in MESSAGE
    projection = ProviderContextProjection(product=PARAPHRASED_PRODUCT, **GROUNDED).to_internal(MESSAGE)
    assert {fact.key for fact in projection.facts} == set(GROUNDED)
    assert projection.masked_keys == ("product",)


def test_literal_and_absent_slots_create_no_mask():
    literal = ProviderContextProjection(product="курса фотографии «KADRTEST»", **GROUNDED).to_internal(MESSAGE)
    assert "product" in {fact.key for fact in literal.facts} and literal.masked_keys == ()
    absent = ProviderContextProjection(**GROUNDED).to_internal(MESSAGE)
    assert absent.masked_keys == ()


def test_incident_strategy_never_takes_product_from_brand_profile():
    svc = strategy_service({**GROUNDED, "product": PARAPHRASED_PRODUCT})
    output = execute(svc)
    # The existing planner question asks for the product instead of substituting another one.
    assert output.kind is ResultKind.NEEDS_INPUT
    assert output.clarification.alternatives == (("product",),)
    svc.graph_service.start_compiled_run.assert_not_awaited()


def test_masked_product_answered_explicitly_runs_with_request_product_only():
    # Same message/request key as the Telegram field answer: the bot adds context.product.
    svc = strategy_service({**GROUNDED, "product": PARAPHRASED_PRODUCT})
    output = execute(svc, context={"product": "курс фотографии «KADRTEST»"})
    assert output.kind is ResultKind.WORKFLOW_STARTED
    assert started_product(svc) == {("курс фотографии «KADRTEST»", "CURRENT_REQUEST")}


def test_absent_product_still_uses_brand_profile_fallback():
    # Unchanged behaviour: a request that does not mention its product keeps durable brand context.
    svc = strategy_service(GROUNDED)
    assert execute(svc).kind is ResultKind.WORKFLOW_STARTED
    assert started_product(svc) == {(BRAND_PRODUCT, "BRAND_PROFILE")}


def test_grounded_product_wins_over_brand_profile():
    svc = strategy_service({**GROUNDED, "product": "курса фотографии «KADRTEST»"})
    assert execute(svc).kind is ResultKind.WORKFLOW_STARTED
    assert started_product(svc) == {("курса фотографии «KADRTEST»", "CURRENT_REQUEST")}


@pytest.mark.parametrize("layer", ["project_run", "brand_profile", "conversation"])
def test_mask_blocks_every_lower_layer(layer):
    projection = NaturalLanguageContextProjection(facts=(), masked_keys=("target_or_target_hypothesis",))
    current = merge_projected_context((), projection, MESSAGE)
    stale = (entry("target", "старая аудитория", layer="lower"),)
    context = ContextResolver().resolve(current_request=current, **{layer: stale})
    labels = {f.label for f in (*context.project_context, *context.known_facts)}
    assert "target_or_target_hypothesis" not in labels


def site_claim(key, text):
    return ContextEntry(key, AuthorizedContextFact(
        fact_id="owned." + key, label=key, input_key=PlanningInputKey(key),
        value={"trust": "site_claim", "source_role": "OWNED_SITE", "snapshot_id": "snap",
               "site_states": [text], "evidence": []},
        source="Owned-site published claim; not independently verified; https://example.test",
        confidence=0.5, module_relevance=frozenset({ModuleId.POSITIONING, ModuleId.VIRTUAL_CMO,
                                                    ModuleId.EXPERIMENTS})))


def test_mask_keeps_owned_site_declared_in_same_request():
    projection = NaturalLanguageContextProjection(facts=(), masked_keys=("product",))
    owned = (site_claim("product", "Курс фотографии для начинающих"),)
    current = merge_projected_context((), projection, MESSAGE, request_scoped=frozenset({"product"}))
    context = ContextResolver().resolve(current_request=current, owned_site_context=owned,
                                        brand_profile=brand_entries({"product": BRAND_PRODUCT}))
    products = [f for f in (*context.project_context, *context.known_facts) if f.label == "product"]
    assert len(products) == 1 and products[0].source.startswith("OWNED_SITE:")


def test_service_passes_owned_site_keys_as_request_scoped():
    svc = strategy_service({**GROUNDED, "product": PARAPHRASED_PRODUCT})
    output = execute(svc, owned=(site_claim("product", "Курс фотографии для начинающих"),))
    assert output.kind is ResultKind.WORKFLOW_STARTED
    assert {source for _, source in started_product(svc)} == {"OWNED_SITE"}


def test_explicit_entry_supersedes_mask_without_duplicate_error():
    projection = NaturalLanguageContextProjection(facts=(), masked_keys=("product",))
    explicit = (entry("product", "курс фотографии «KADRTEST»"),)
    merged = merge_projected_context(explicit, projection, MESSAGE)
    assert merged == explicit


def test_mask_logs_only_field_names(caplog):
    projection = ProviderContextProjection(product="PRIVATE PARAPHRASE").to_internal("PRIVATE BUSINESS VALUE")
    with caplog.at_level("INFO", logger="app.marketing_copilot.context_projection"):
        merge_projected_context((), projection, "PRIVATE BUSINESS VALUE")
    assert "masked_fields=['product']" in caplog.text and "PRIVATE" not in caplog.text


@pytest.mark.parametrize("masked", [("product", "product"), ("unknown_key",)])
def test_invalid_masks_fail_closed(masked):
    with pytest.raises(ValueError):
        NaturalLanguageContextProjection(facts=(), masked_keys=masked)


def test_mask_cannot_overlap_projected_fact():
    with pytest.raises(ValueError):
        NaturalLanguageContextProjection(facts=(BusinessFactCandidate(key="product", value="KADRTEST"),),
                                         masked_keys=("product",))


def interpretation(masked=()):
    return InterpretedRequest(intent=intent(IntentKind.MARKETING_STRATEGY),
                              projection=NaturalLanguageContextProjection(
                                  facts=(BusinessFactCandidate(key="business_goal", value=GROUNDED["business_goal"]),),
                                  masked_keys=masked))


def test_persisted_masks_roundtrip_and_empty_masks_keep_legacy_shape():
    masked = interpretation(("product",))
    raw = masked.model_dump(mode="json")
    assert raw["projection"]["masked_keys"] == ["product"]
    assert validate_interpretation(raw, MESSAGE) == masked
    # Rows without masks keep the exact pre-change JSON shape, readable by the previous release.
    legacy = interpretation().model_dump(mode="json")
    assert set(legacy["projection"]) == {"facts"}
    assert validate_interpretation(legacy, MESSAGE) == interpretation()


def test_corrupted_persisted_mask_fails_closed():
    raw = copy.deepcopy(interpretation(("product",)).model_dump(mode="json"))
    raw["projection"]["masked_keys"] = ["business_goal"]  # overlaps a projected fact
    with pytest.raises(CopilotContractError, match="Invalid persisted"):
        validate_interpretation(raw, MESSAGE)
