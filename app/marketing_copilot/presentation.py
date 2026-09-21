"""Deterministic public projections of fully accepted results; no model calls."""
from urllib.parse import urlsplit, urlunsplit

from app.module_execution.executors.common import plain
from app.module_execution.executors.schemas import CompetitorOutput, PositioningOutput, CreatorOutput
from app.module_execution.executors.intelligence_schemas import MarketOutput, StrategyOutput, ExperimentsOutput
from app.module_registry import ModuleId
from app.product_context.contracts import KnowledgeKind
from app.product_context.projection import PRODUCT_TRUTH_FIELDS
from app.services.safe_http import validate_url, UnsafeURL
from . import api_contracts as dto

SCHEMAS = {ModuleId.COMPETITOR_ANALYSIS: CompetitorOutput, ModuleId.POSITIONING: PositioningOutput,
    ModuleId.CREATOR: CreatorOutput, ModuleId.MARKET_ANALYSIS: MarketOutput,
    ModuleId.VIRTUAL_CMO: StrategyOutput, ModuleId.EXPERIMENTS: ExperimentsOutput}


def owned_result(acquired, *, candidates=False):
    snapshot = acquired.snapshot
    return dto.OwnedSiteResult(outcome=acquired.outcome.value,
        snapshot_id=snapshot.snapshot_id if snapshot else None,
        candidates=[dto.ConfirmationCandidate(statement_id=s.statement_id, field=s.field.value,
            statement=s.text, source_url=snapshot.canonical_url) for s in snapshot.statements
            if s.kind is KnowledgeKind.OBSERVATION and s.field in PRODUCT_TRUTH_FIELDS]
            if snapshot and candidates else [])


def limitations(result, wire):
    return list(dict.fromkeys([*wire.limitations, *wire.assumptions,
                              *(item.description for item in result.normalized_result.limitations if item.description)]))[:64]


def sources(result):
    values = []
    for evidence in result.normalized_result.evidence:
        provenance = evidence.provenance
        url = None
        for prefix in ("Observable public page: ", "Observed source page (its assertions are not independently verified): "):
            if provenance.startswith(prefix):
                candidate = provenance[len(prefix):].split(";", 1)[0]
                try:
                    validate_url(candidate)
                    parsed = urlsplit(candidate)
                    url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
                except (UnsafeURL, ValueError):
                    pass
        label = "Public page; published assertions are not independently verified" if url else (
            "Supplied business context; not independently verified" if evidence.source_class.value == "FIRST_PARTY"
            else "Caller-supplied source excerpt; not independently verified")
        summary = dto.SourceSummary(label=label, url=url)
        if summary not in values:
            values.append(summary)
    return values[:64]


def module_presentation(result):
    wire = SCHEMAS[result.module_id].model_validate(plain(result.payload))
    limits = limitations(result, wire)
    if result.module_id is ModuleId.CREATOR:
        return dto.Post(**wire.post.model_dump(), limitations=limits)
    if result.module_id is ModuleId.VIRTUAL_CMO:
        sections = {s.output_name.rstrip("."): dto.StrategySection(text=s.text, items=s.items) for s in wire.outputs}
        return dto.Strategy(**sections, limitations=limits)
    if result.module_id is ModuleId.EXPERIMENTS:
        return dto.Experiments(designs=[dto.Experiment(**e.model_dump(exclude={"related_strategic_claim_ids"}))
            for e in wire.experiments], limitations=limits)
    return dto.Findings(kind=result.module_id.value.lower(), findings=[dto.Finding(
        topic=s.output_name.rstrip("."), text=s.text, kind=s.kind, confidence=s.confidence) for s in wire.outputs],
        sources=sources(result), limitations=limits)


COVERAGE_MESSAGES = {
    "market_research_not_supplied": "Market research was not supplied.",
    "competitor_research_not_supplied": "Competitor research was not supplied.",
    "only_one_competitor_analyzed": "Only one competitor was analyzed.",
    "economics_unavailable": "Economics are unavailable; profitability and affordability remain unknown.",
}


def coverage_presentation(raw, nodes):
    if not raw or raw.get("schema_version") != "evidence_coverage.v1":
        return None
    messages = []
    for item in raw.get("limitations", []):
        code = item.get("code")
        if code == "optional_node_failed":
            module = nodes.get(item.get("node_id"))
            messages.append({ModuleId.COMPETITOR_ANALYSIS: "One competitor analysis is unavailable.",
                ModuleId.MARKET_ANALYSIS: "Market research is unavailable.",
                ModuleId.EXPERIMENTS: "Experiments are unavailable."}.get(module, "An optional result is unavailable."))
        else:
            messages.append(COVERAGE_MESSAGES.get(code, "Evidence coverage is limited."))
    return dto.Coverage(competitors_supplied=raw.get("competitors_supplied", 0),
        competitors_accepted=raw.get("competitors_accepted", 0), limitations=list(dict.fromkeys(messages)))


def calculation_presentation(value):
    inputs = {k: str(v) for k, v in value.inputs.model_dump().items() if k != "target" and v is not None}
    outputs = {k: str(getattr(value, k)) for k in ("clicks", "leads", "required_traffic", "required_budget")
               if getattr(value, k) is not None}
    return dto.Calculation(calculation_type=value.inputs.target.value, formula=value.formula,
        inputs=dto.CalculationInputs(**inputs), outputs=dto.CalculationOutputs(**outputs), assumptions=list(value.assumptions))
