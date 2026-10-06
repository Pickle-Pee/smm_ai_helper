"""Positioning from explicit product truth and optional predecessor results."""
from app.marketing_orchestrator.quality_gates.contracts import BlockingReason, ClaimType
from app.module_registry import ModuleId

from .common import BaseExecutor, blocked, facts_for, first_party_evidence, scoped_facts
from .schemas import PositioningOutput

POSITIONING_INPUTS = ("product", "target_or_target_hypothesis", "product_truth")
POSITIONING_SEEDS = ("customer_job_or_need", "relevant_alternative")
_SEED_OUTPUTS = {
    "customer_job_or_need": frozenset({"JTBD_frame", "demand_context"}),
    "relevant_alternative": frozenset({"category", "frame_of_reference", "points_of_parity"}),
}
_SEED_LIMITATIONS = {
    "customer_job_or_need": "customer_job_or_need was not supplied; customer job and demand context are hypotheses requiring validation.",
    "relevant_alternative": "relevant_alternative was not supplied; category, frame of reference and points of parity are hypotheses requiring validation.",
}


class PositioningExecutor(BaseExecutor):
    module_id = ModuleId.POSITIONING
    executor_key = "positioning.v1"
    schema_version = "positioning.payload.v1"
    output_type = PositioningOutput
    instruction = """Develop the requested positioning outputs: category/frame, target/customer job,
value proposition, differentiation, RTB, positioning, USP directions, offer and
message hierarchy as requested. Ground product promises and RTB in supplied product
truth/proof; a positioning statement is not a slogan. Never invent uniqueness or
customer quotes. For differentiation, points_of_difference and USP_directions,
kind must always be HYPOTHESIS, including when based on supplied product truth.
For RTB, value_proposition, positioning_statement and offer, evidence_ids must
include at least one supplied local_evidence ID whose input_key is product_truth
or existing_proof. Parent claims alone do not satisfy this requirement. Never
invent evidence IDs. customer_job_or_need and relevant_alternative are optional
strategic seeds: use them when supplied, and otherwise derive reasoning as explicit
HYPOTHESIS. Without customer_job_or_need, JTBD_frame and demand_context must be
HYPOTHESIS. Without relevant_alternative, category, frame_of_reference and
points_of_parity must be HYPOTHESIS. Only a cited accepted OBSERVATION with the
same output name and its own evidence can independently support an exception.
Never treat an upstream hypothesis as observed evidence. Cite materially used
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

    def build_result(self, request, output, evidence, parents):
        # Preserve missing-seed limitations even when the provider omits them.
        supplied = {item.input_key for item in evidence}
        limitations = [_SEED_LIMITATIONS[key] for key in POSITIONING_SEEDS if key not in supplied]
        # Reserve schema-bounded slots for server-owned notices; provider output
        # may already fill every available limitation slot.
        limit = self.output_type.model_json_schema()["properties"]["limitations"]["maxItems"]
        combined = list(dict.fromkeys((*limitations, *output.limitations)))[:limit]
        output = self.output_type.model_validate({**output.model_dump(), "limitations": combined})
        return super().build_result(request, output, evidence, parents)

    def validate_statement(self, statement, local, parents):
        supplied = {item.input_key for item in local.values()}
        for seed, outputs in _SEED_OUTPUTS.items():
            if seed in supplied or statement.output_name not in outputs or statement.kind == "HYPOTHESIS":
                continue
            # Mere parent presence or a different factual output cannot authorize
            # factual customer/competitive reasoning. Accepted identity and scope
            # are checked by BaseExecutor before this structural support check.
            supported = any(
                parents[pid].declared_output_name == statement.output_name
                and parents[pid].claim_type is ClaimType.OBSERVATION
                and parents[pid].evidence_ids
                for pid in statement.parent_claim_ids
            )
            if not supported:
                raise ValueError("Missing strategic seed requires hypothesis marking or matching factual parent evidence")
        if statement.output_name in ("differentiation", "points_of_difference", "USP_directions") and statement.kind != "HYPOTHESIS":
            raise ValueError("Differentiation requires hypothesis marking in v1")
        if statement.output_name in ("RTB", "value_proposition", "positioning_statement", "offer"):
            if not any(local[e].input_key in ("product_truth", "existing_proof") for e in statement.evidence_ids):
                raise ValueError("Product claims must cite supplied product truth/proof")
