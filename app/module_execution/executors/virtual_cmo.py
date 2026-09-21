"""Bounded strategic synthesis, never planning, routing or scheduling."""
from dataclasses import replace
import json

from app.marketing_orchestrator.quality_gates.contracts import BlockingReason
from app.module_registry import ModuleId

from .common import blocked, facts_for, first_party_evidence, scoped_facts
from .intelligence_common import IntelligenceExecutor, require_supported_numbers, supported_text
from .intelligence_schemas import StrategyOutput


class VirtualCMOExecutor(IntelligenceExecutor):
    module_id = ModuleId.VIRTUAL_CMO
    executor_key = "virtual_cmo.v1"
    schema_version = "virtual_cmo.payload.v1"
    output_type = StrategyOutput
    instruction = """Synthesize a focused strategy for the explicit business goal and decision object.
You are a strategic expert, not an orchestrator, planner, router or scheduler.
Use accepted positioning, market, competitor and other supplied findings only.
Every material finding needs first-party support or parent claims. When upstream
findings are available, cite material parents in each strategic output.
Give one main_growth_constraint hypothesis with exactly one item, and at most three
items per other output: priorities, trade-offs, resource priorities, bets, roadmap,
risks and decision triggers. Roadmap items are hypotheses/recommendations supported
by the same cited parents and assumptions. No generic catalogue of marketing advice.
Missing economics means unknown profitability and resource affordability, not a
license to invent budgets or unit economics. No new market/economic facts.
Only HYPOTHESIS or RECOMMENDATION kinds. Numerical statements must quote supplied
support verbatim. Qualitative resource prioritization is allowed without economics."""
    limitation = "Strategic synthesis of supplied context only; missing market or economics evidence cannot support factual market, profitability or affordability claims."

    async def execute(self, request):
        early = self.prepare(request)
        if early is not None:
            return early
        facts = scoped_facts(request)
        if not facts_for(facts, "business_goal"):
            return blocked(request, self.schema_version, BlockingReason.MISSING_BLOCKING_INPUT, "Explicit business_goal required")
        if not any(facts_for(facts, k) for k in ("known_business_context", "known_business_context.", "product", "product_or_category")):
            return blocked(request, self.schema_version, BlockingReason.MISSING_BLOCKING_INPUT, "Known business/product decision object required")
        return await self.generate(request, first_party_evidence(request, facts))

    def build_result(self, request, output, evidence, parents):
        if not any(facts_for(scoped_facts(request), k) for k in ("economics", "unit_economics")):
            output.limitations = list(dict.fromkeys((*output.limitations,
                "Economics absent: profitability, budget affordability and unit economics are unknown; resource priorities are qualitative.")))
        result = super().build_result(request, output, evidence, parents)
        # Structured item text is material too: include it in the very same claim,
        # with exactly the validated support and confidence, not an ungated payload.
        claims = tuple(replace(claim, value=json.dumps({"summary": statement.text, "items": statement.items}, ensure_ascii=False))
                       for claim, statement in zip(result.normalized_result.claims, output.outputs))
        return replace(result, payload=output.model_dump(mode="json"),
                       normalized_result=replace(result.normalized_result, claims=claims))

    def validate_statement(self, statement, local, parents):
        super().validate_statement(statement, local, parents)
        if statement.kind not in ("HYPOTHESIS", "RECOMMENDATION"):
            raise ValueError("Synthesis must not introduce new factual claims")
        if parents and not statement.parent_claim_ids:
            raise ValueError("Strategic synthesis with predecessors must cite parent claims")
        if statement.output_name == "main_growth_constraint" and (
                len(statement.items) != 1 or statement.kind != "HYPOTHESIS"):
            raise ValueError("Exactly one main growth constraint hypothesis required")
        for item in statement.items:
            require_supported_numbers(item, supported_text(statement, local, parents))
