"""Bounded strategy topology and explicitly scoped research, without I/O."""
from collections.abc import Mapping
from dataclasses import replace
from urllib.parse import urlsplit, urlunsplit

from app.module_registry import ModuleId
from .contracts import AuthorizedContextFact, PlanningInputKey, Sensitivity

SCENARIO = "strategy_builder_v1"
REQUIRED_KEYS = (
    "business_goal", "product", "target_or_target_hypothesis", "customer_job_or_need",
    "relevant_alternative", "product_truth",
)
MARKET_KEYS = frozenset({"market_sources", "market_source_urls", "existing_customers",
                         "internal_sales_data", "current_segments", "research", "customer_findings"})
SOURCE_KEYS = MARKET_KEYS | {"competitor_urls", "competitor_url", "competitor_or_category_scope", "observable_evidence"}


def nonempty(value):
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, Mapping):
        return any(nonempty(v) for v in value.values())
    if isinstance(value, tuple):
        return any(nonempty(v) for v in value)
    return True


def key(fact):
    return fact.input_key.value if fact.input_key else fact.label


def normalize_competitors(values):
    if type(values) not in (tuple, list) or len(values) > 128:
        raise ValueError("competitor_urls must be a bounded URL list")
    result = set()
    for value in values:
        if (type(value) is not str or not 1 <= len(value) <= 2048
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value):
            raise ValueError("invalid competitor URL")
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            raise ValueError("invalid competitor URL")
        host = parsed.hostname.encode("idna").decode("ascii").lower()
        host = "[" + host + "]" if ":" in host else host
        port = parsed.port
        if port is not None and port != {"http": 80, "https": 443}[parsed.scheme]:
            host += ":" + str(port)
        result.add(urlunsplit((parsed.scheme, host, parsed.path or "/", parsed.query, "")))
    if len(result) > 3:
        raise ValueError("at most three unique competitors")
    return tuple(sorted(result))


def strategy_topology(nodes, edges):
    """Validate both source and compiled graphs; returns research node identities."""
    pairs = [(n.node_id, n.module_id) for n in nodes]
    research = []
    if pairs and pairs[0] == ("market_analysis", ModuleId.MARKET_ANALYSIS):
        research.append(pairs.pop(0)[0])
    for index in range(1, 4):
        if pairs and pairs[0] == (f"competitor_analysis_{index}", ModuleId.COMPETITOR_ANALYSIS):
            research.append(pairs.pop(0)[0])
        else:
            break
    if pairs != [("positioning", ModuleId.POSITIONING), ("virtual_cmo", ModuleId.VIRTUAL_CMO),
                 ("experiments", ModuleId.EXPERIMENTS)]:
        raise ValueError("invalid strategy nodes")
    expected = sorted([(n, "positioning") for n in research] +
                      [("positioning", "virtual_cmo"), ("virtual_cmo", "experiments")], key=lambda e: (e[1], e[0]))
    if [(e.upstream_node_id, e.downstream_node_id) for e in edges] != expected:
        raise ValueError("invalid strategy edges")
    urls = []
    for node in nodes:
        facts = (*node.context_packet.known_facts, *node.context_packet.relevant_project_context)
        source_keys = {key(f) for f in facts} & SOURCE_KEYS
        if node.module_id is ModuleId.COMPETITOR_ANALYSIS:
            sources = [f.value for f in facts if key(f) == "competitor_url"]
            if len(sources) != 1 or source_keys != {"competitor_url"}:
                raise ValueError("competitor node requires only its own scoped source")
            urls.extend(sources)
        elif node.module_id is ModuleId.MARKET_ANALYSIS:
            if not source_keys or not source_keys <= MARKET_KEYS:
                raise ValueError("market node requires explicit scoped research")
        elif source_keys:
            raise ValueError("raw research sources cannot bypass research nodes")
    if tuple(urls) != normalize_competitors(urls):
        raise ValueError("competitor nodes must have unique sorted canonical sources")
    return tuple(research)


def scoped_packet(planner, context, module, interpretation, *, competitor=None):
    packet = planner._context_packet(context, module, SCENARIO, (), interpretation.constraints)
    def select(facts):
        return tuple(f for f in facts if f.sensitivity is not Sensitivity.SECRET and nonempty(f.value)
                     and (key(f) not in SOURCE_KEYS or (module is ModuleId.MARKET_ANALYSIS and key(f) in MARKET_KEYS)))
    packet = replace(packet, known_facts=select(packet.known_facts),
                     relevant_project_context=select(packet.relevant_project_context), evidence=(), upstream_findings=())
    facts = (*packet.relevant_project_context, *packet.known_facts)
    additions = []
    if competitor is not None:
        additions.append(AuthorizedContextFact("strategy.competitor.source", "competitor_url", competitor,
            source="explicit scoped competitor_urls; unverified fetch target", module_relevance=frozenset({module})))
    if module is ModuleId.MARKET_ANALYSIS and not any(key(f) == "product_or_category" for f in facts):
        product = next((f for f in facts if key(f) == "product"), None)
        if product:
            # Exact first-party value and provenance, not new product evidence.
            from .planner import _stable_value
            additions.append(replace(product, fact_id="strategy.market.product", value=_stable_value(product.value),
                                     label="product_or_category", input_key=PlanningInputKey.PRODUCT_OR_CATEGORY))
    return replace(packet, known_facts=(*packet.known_facts, *additions),
                   evidence=tuple(sorted({e for f in facts for e in f.evidence})))
