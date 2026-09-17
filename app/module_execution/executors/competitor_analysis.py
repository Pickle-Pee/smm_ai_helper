"""Observable single-public-page competitor analysis, without search discovery."""
from typing import Protocol, Any

from app.marketing_orchestrator.quality_gates.contracts import (
    BlockingReason, Confidence, EvidenceRecord, EvidenceSourceClass,
)
from app.module_registry import ModuleId, ToolCapability
from app.services.safe_http import UnsafeURL, validate_url

from .common import BaseExecutor, LocalEvidence, blocked, facts_for, first_party_evidence, scoped_facts, stable_id
from .schemas import CompetitorOutput


class SiteAnalyzer(Protocol):
    """Cache-free safe URL capability; provider failures must propagate once."""
    async def analyze(self, url: str) -> Any: ...


class CompetitorAnalysisExecutor(BaseExecutor):
    module_id = ModuleId.COMPETITOR_ANALYSIS
    executor_key = "competitor_analysis.v1"
    schema_version = "competitor_analysis.payload.v1"
    output_type = CompetitorOutput
    instruction = """Analyze observable positioning, offers, proof and communication on one supplied
public competitor page. Evidence of a page statement is not proof that the statement
is true. Strengths/weaknesses are communication inferences. Competitor sets,
substitutes, market gaps and differentiation beyond the page are explicitly bounded
hypotheses, never a market census. Explain missing coverage in limitations."""
    limitation = "One public page only; no market-wide coverage, independent proof of commercial success or customer research."

    def __init__(self, *, model_call, analyzer: SiteAnalyzer | None, composer=None):
        super().__init__(model_call=model_call, composer=composer)
        self._analyzer = analyzer

    async def execute(self, request):
        early = self.prepare(request)
        if early is not None:
            return early
        facts = scoped_facts(request)
        urls = facts_for(facts, "competitor_url")
        # A planner may explicitly carry a URL in its existing typed scope slot.
        if not urls:
            urls = tuple(f for f in facts_for(facts, "competitor_or_category_scope")
                         if isinstance(f.value, str) and f.value.startswith(("http://", "https://")))
        if len(urls) != 1 or type(urls[0].value) is not str:
            return blocked(request, self.schema_version, BlockingReason.MISSING_BLOCKING_INPUT,
                           "Supply exactly one explicit competitor_url; name/category search is unavailable")
        try:
            validate_url(urls[0].value)
        except UnsafeURL:
            return blocked(request, self.schema_version, BlockingReason.AUTHORIZATION_REQUIRED, "Public URL required")
        if self._analyzer is None or ToolCapability.SITE_FETCH not in request.context_packet.available_tools:
            return blocked(request, self.schema_version, BlockingReason.TOOL_UNAVAILABLE, "Authorized site_fetch capability required")
        data = await self._analyzer.analyze(urls[0].value)
        sources = data.url_summaries if data is not None else []
        evidence = list(first_party_evidence(request, facts))
        for index, source in enumerate(sources):
            if not source.get("ok"):
                continue
            excerpt = "\n".join((source.get("title", ""), source.get("meta_description", ""),
                                  "\n".join(source.get("h1", [])), source.get("main_text_excerpt", ""))).strip()
            if not excerpt:
                continue
            final_url = source.get("final_url", source.get("url", ""))
            validate_url(final_url)
            evidence.append(LocalEvidence(
                EvidenceRecord(stable_id("evd", request, "page", str(index)), EvidenceSourceClass.EXTERNAL_PRIMARY,
                               f"Observable public page: {final_url}; not independent verification of its assertions"),
                excerpt[:8000], Confidence.MEDIUM,
            ))
        if not any(e.record.source_class is EvidenceSourceClass.EXTERNAL_PRIMARY for e in evidence):
            return blocked(request, self.schema_version, BlockingReason.MISSING_BLOCKING_INPUT, "No observable public-page evidence")
        return await self.generate(request, tuple(evidence))

    def validate_statement(self, statement, local, parents):
        if not any(local[e].record.source_class is EvidenceSourceClass.EXTERNAL_PRIMARY for e in statement.evidence_ids):
            raise ValueError("Competitor analysis requires local public-page support")
        if statement.output_name in ("direct_competitors", "indirect_competitors", "substitutes", "market_gaps",
                                     "differentiation_hypotheses.") and statement.kind not in ("HYPOTHESIS", "RECOMMENDATION"):
            raise ValueError("Single-page analysis cannot assert market-wide conclusions")
