"""Positioning from explicit product truth and optional predecessor results."""
from app.marketing_orchestrator.quality_gates.contracts import BlockingReason
from app.module_registry import ModuleId

from .common import BaseExecutor, blocked, facts_for, first_party_evidence, scoped_facts
from .schemas import PositioningOutput

POSITIONING_INPUTS = ("product", "target_or_target_hypothesis", "customer_job_or_need",
                      "relevant_alternative", "product_truth")


class PositioningExecutor(BaseExecutor):
    module_id = ModuleId.POSITIONING
    executor_key = "positioning.v1"
    schema_version = "positioning.payload.v1"
    output_type = PositioningOutput
    instruction = """Develop the requested positioning outputs: category/frame, target/customer job,
value proposition, differentiation, RTB, positioning, USP directions, offer and
message hierarchy as requested. Ground product promises and RTB in supplied product
truth/proof; a positioning statement is not a slogan. Never invent uniqueness or
customer quotes. Differentiation is a hypothesis to validate. Cite materially used
COMPETITOR_ANALYSIS/MARKET_ANALYSIS predecessor claims via parent_claim_ids."""
    limitation = "Positioning uses supplied product truth and optional predecessor claims; uniqueness and customer response require validation."

    async def execute(self, request):
        early = self.prepare(request)
        if early is not None:
            return early
        facts = scoped_facts(request)
        missing = [key for key in POSITIONING_INPUTS if not facts_for(facts, key)]
        if missing:
            return blocked(request, self.schema_version, BlockingReason.MISSING_BLOCKING_INPUT, ", ".join(missing))
        return await self.generate(request, first_party_evidence(request, facts))

    def validate_statement(self, statement, local, parents):
        if statement.output_name in ("differentiation", "points_of_difference", "USP_directions") and statement.kind != "HYPOTHESIS":
            raise ValueError("Differentiation requires hypothesis marking in v1")
        if statement.output_name in ("RTB", "value_proposition", "positioning_statement", "offer"):
            if not any(local[e].input_key in ("product_truth", "existing_proof") for e in statement.evidence_ids):
                raise ValueError("Product claims must cite supplied product truth/proof")
