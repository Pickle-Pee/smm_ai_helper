"""Supplied-source market analysis. No search provider or model prior as evidence."""
from pydantic import ValidationError

from app.marketing_orchestrator.quality_gates.contracts import (
    BlockingReason, Confidence, EvidenceRecord, EvidenceSourceClass,
)
from app.module_registry import ModuleId, ToolCapability
from app.services.safe_http import UnsafeURL, validate_url

from .common import (LocalEvidence, blocked, facts_for, first_party_evidence,
                     parent_claims, plain, scoped_facts, stable_id)
from .intelligence_common import IntelligenceExecutor
from .intelligence_schemas import MarketOutput, SuppliedMarketSource


class MarketAnalysisExecutor(IntelligenceExecutor):
    module_id = ModuleId.MARKET_ANALYSIS
    executor_key = "market_analysis.v1"
    schema_version = "market_analysis.payload.v1"
    output_type = MarketOutput
    instruction = """Analyze only supplied market/customer evidence and approved predecessors.
No search, prior model knowledge, fabricated citations or external market facts.
Define the market before sizing. Preserve primary versus secondary source classes.
First-party facts describe the company's experience, not the entire market.
Observations quote supplied support verbatim. Numbers may only occur in verbatim
supported statements, never invented TAM/SAM/SOM, growth, share or customer statistics.
Without numerical sizing evidence, market_size_if_supported is an unknown hypothesis
without numbers. Category, demand, segments, JTBD, CEP, alternatives, opportunities
and white spaces beyond observations are hypotheses, with explicit research gaps.
Use all canonical requested names including punctuation. No hidden reasoning."""
    limitation = "Source-backed analysis only; no autonomous search or market census. Unsupported market size, growth, share and behavior remain unknown."

    def __init__(self, *, model_call, analyzer=None, composer=None):
        super().__init__(model_call=model_call, composer=composer)
        self._analyzer = analyzer

    async def execute(self, request):
        early = self.prepare(request)
        if early is not None:
            return early
        facts = scoped_facts(request)
        if not facts_for(facts, "product_or_category"):
            return blocked(request, self.schema_version, BlockingReason.MISSING_BLOCKING_INPUT,
                           "Supply product_or_category")
        source_facts = facts_for(facts, "market_sources")
        targets = facts_for(facts, "market_source_urls")
        evidence = list(first_party_evidence(request, tuple(f for f in facts if f not in (*source_facts, *targets))))
        try:
            for fact in source_facts:
                rows = plain(fact.value)
                if not isinstance(rows, list) or not 1 <= len(rows) <= 8:
                    raise ValueError("Supply one to eight source records")
                for index, row in enumerate(rows):
                    source = SuppliedMarketSource.model_validate(row)
                    evidence.append(LocalEvidence(EvidenceRecord(
                        stable_id("evd", request, "supplied", fact.fact_id, str(index)),
                        EvidenceSourceClass(source.source_class),
                        "Supplied source excerpt: " + source.source_reference),
                        source.excerpt, Confidence.MEDIUM, "market_sources"))
            urls = [url for fact in targets for url in plain(fact.value)]
            if targets and (any(not isinstance(plain(f.value), list) for f in targets)
                            or not 1 <= len(urls) <= 3 or any(type(url) is not str for url in urls)):
                raise ValueError("Supply one to three public source URLs")
            for url in urls:
                validate_url(url)
        except (ValueError, TypeError, ValidationError):
            return blocked(request, self.schema_version, BlockingReason.MISSING_BLOCKING_INPUT,
                           "Invalid supplied market source records or public URLs")
        if urls and (self._analyzer is None or ToolCapability.SITE_FETCH not in request.context_packet.available_tools):
            return blocked(request, self.schema_version, BlockingReason.TOOL_UNAVAILABLE,
                           "Supplied URLs require authorized injected safe site analysis")
        for index, url in enumerate(urls):
            data = await self._analyzer.analyze(url)
            for page_index, page in enumerate(data.url_summaries if data is not None else ()):
                if not page.get("ok"):
                    continue
                excerpt = page.get("main_text_excerpt", "").strip()
                if not excerpt:
                    continue
                final_url = page.get("final_url", page.get("url", url))
                try:
                    validate_url(final_url)
                except UnsafeURL:
                    return blocked(request, self.schema_version, BlockingReason.AUTHORIZATION_REQUIRED,
                                   "Source returned a non-public URL")
                evidence.append(LocalEvidence(EvidenceRecord(
                    stable_id("evd", request, "page", str(index), str(page_index)),
                    EvidenceSourceClass.EXTERNAL_PRIMARY,
                    "Observed source page (its assertions are not independently verified): " + final_url),
                    excerpt[:8000], Confidence.MEDIUM, "market_sources"))
        research_keys = ("existing_customers", "internal_sales_data", "current_segments", "research", "customer_findings")
        if not source_facts and not any(e.input_key == "market_sources" for e in evidence) and not any(
                facts_for(facts, key) for key in research_keys) and not parent_claims(request):
            return blocked(request, self.schema_version, BlockingReason.MISSING_BLOCKING_INPUT,
                           "Supply market/customer findings, source excerpts or accepted upstream results")
        return await self.generate(request, tuple(evidence))

    def validate_statement(self, statement, local, parents):
        super().validate_statement(statement, local, parents)
        external = any(local[e].record.source_class in (
            EvidenceSourceClass.EXTERNAL_PRIMARY, EvidenceSourceClass.EXTERNAL_SECONDARY
        ) for e in statement.evidence_ids)
        if statement.kind not in ("OBSERVATION", "HYPOTHESIS", "RECOMMENDATION"):
            raise ValueError("Market inference must remain an explicit hypothesis")
        if statement.output_name == "market_size_if_supported" and not external:
            if statement.kind != "HYPOTHESIS" or any(c.isdigit() for c in statement.text):
                raise ValueError("Market size without external numerical support must remain unknown")
