"""Server-owned fact provenance and explicit public source-role mapping."""
from app.marketing_orchestrator import AuthorizedContextFact, PlanningInputKey
from app.module_registry import ModuleId
from .context_resolver import ContextEntry

MODULES = frozenset({ModuleId.COMPETITOR_ANALYSIS, ModuleId.POSITIONING, ModuleId.CREATOR,
                     ModuleId.MARKET_ANALYSIS, ModuleId.VIRTUAL_CMO, ModuleId.EXPERIMENTS})
SCENARIOS = frozenset({"explicit_single_module_v1", "competitive_positioning_v1", "strategy_builder_v1"})
ALIASES = {"target": "target_or_target_hypothesis"}


def entry(key, value, *, layer="request"):
    canonical = ALIASES.get(key, key)
    typed = next((k for k in PlanningInputKey if k.value == canonical), None)
    return ContextEntry(canonical, AuthorizedContextFact(
        fact_id=f"http.{layer}.{canonical}", label=canonical, input_key=typed, value=value,
        source=f"Authenticated {layer} business input; not independently verified",
        confidence=.7, module_relevance=MODULES, scenario_relevance=SCENARIOS))


def current_entries(payload):
    fields = payload.context.model_dump(exclude_unset=True)
    entries = [entry(k, v) for k, v in fields.items()]
    # The public API authorizes source roles only through these fields. Explicit
    # empty masks disable the internal legacy raw-message URL fallback too.
    entries.extend((entry("competitor_urls", payload.competitor_urls),
        entry("competitor_or_category_scope", payload.competitor_urls[0] if len(payload.competitor_urls) == 1 else None),
        entry("market_source_urls", payload.market_source_urls),
        entry("market_sources", [{"source_reference": s.title, "excerpt": s.excerpt,
                                  "source_class": "EXTERNAL_SECONDARY"} for s in payload.market_sources]),
        entry("asset_format", "text_post")))
    return tuple(entries)


def brand_entries(values):
    # Never accept arbitrary extra_json as authority metadata or source roles.
    aliases = {"product_description": "product", "audience": "target", "tone": "tone"}
    mapped = {aliases[k]: v for k, v in values.items() if k in aliases and isinstance(v, str) and len(v) <= 4000}
    goals = values.get("goals")
    if isinstance(goals, list) and len(goals) <= 10 and all(isinstance(v, str) for v in goals):
        mapped["business_goal"] = "; ".join(goals)[:4000]
    for key in ("business_goal", "product", "target", "customer_job_or_need", "relevant_alternative",
                "product_truth", "existing_proof", "geography", "economics", "message"):
        value = values.get(key)
        if key not in mapped and isinstance(value, str) and len(value) <= 4000:
            mapped[key] = value
    return tuple(entry(k, v, layer="brand") for k, v in mapped.items())
