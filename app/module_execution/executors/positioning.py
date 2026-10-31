"""Positioning from explicit product truth and optional predecessor results."""
from app.marketing_orchestrator.quality_gates.contracts import BlockingReason, ClaimType
from app.module_registry import ModuleId, ModuleRegistry
from app.model_generation_policy import ModuleOutputBudget

from .common import (
    BaseExecutor, SemanticRule, StatementSemanticsError, blocked, facts_for,
    first_party_evidence, scoped_facts, log,
)
from .provider_schema import (
    SchemaProjectionError, collapse_single_support_anyof, single_support_anyof_count, schema_measurement,
)
from .positioning_provider_schema import minimal_positioning_schema
from .positioning_observation_schema import positioning_observation_schema
from .intelligence_common import require_supported_numbers, supported_text
from .schemas import (
    PositioningOutput, PositioningWithoutAlternativeOutput, PositioningWithoutJobOutput,
    PositioningWithoutSeedsOutput,
)
from .product_support import (
    PRODUCT_OUTPUTS, PRODUCT_CATEGORIES, WIRE_VERSION, product_wire_schema, decode_product_wire,
)

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
points_of_parity must be HYPOTHESIS, including when citing accepted factual parents.
Never treat an upstream hypothesis as observed evidence. Cite materially used
COMPETITOR_ANALYSIS/MARKET_ANALYSIS predecessor claims via parent_claim_ids.
Within each statement, evidence_ids and parent_claim_ids must each contain unique
IDs. Cite each source once per array; do not repeat the product-truth ID when it
already appears among that statement's evidence_ids.
Keep statements qualitative, without digits or numbered lists, unless the entire
statement is copied verbatim from its cited local evidence or accepted parent
assertion. Never invent numeric thresholds, sample sizes, budgets or deadlines,
or calculate or combine numbers from sources into a new assertion.
Observations must quote one actually cited local source or accepted factual parent
verbatim; an upstream hypothesis is not observed evidence. Use HYPOTHESIS or
INFERENCE for unsupported reasoning. Provider generation permits INFERENCE,
HYPOTHESIS and RECOMMENDATION only, subject to the stricter output-specific kinds."""
    limitation = "Positioning uses supplied product truth and optional predecessor claims; uniqueness and customer response require validation."

    def __init__(self, *, model_call, composer=None, provider_schema_projection=False,
                 product_support_wire=False, minimal_provider_schema=False):
        if type(minimal_provider_schema) is not bool:
            raise TypeError("Expected boolean POSITIONING minimal provider schema policy")
        if minimal_provider_schema and (provider_schema_projection or product_support_wire):
            raise ValueError("POSITIONING minimal schema requires other POSITIONING experiments disabled")
        self._minimal_provider_schema = minimal_provider_schema
        if type(provider_schema_projection) is not bool:
            raise TypeError("Expected boolean POSITIONING projection policy")
        super().__init__(model_call=model_call, composer=composer)
        self._provider_schema_projection = provider_schema_projection
        if type(product_support_wire) is not bool:
            raise TypeError("Expected boolean POSITIONING product support wire policy")
        self._product_support_wire = product_support_wire
        if product_support_wire:
            self.instruction += f"\nUse wire_contract_version {WIRE_VERSION}. For each of " + ", ".join(sorted(PRODUCT_OUTPUTS)) + """:
select product_support_id explicitly from AllowedProductSupportId. It is mandatory
for every kind, including HYPOTHESIS. evidence_ids contains only additional local
support (at most 31); do not repeat the selected ID there. parent_claim_ids remains
available for materially used accepted parents. No inferred or fabricated IDs."""

    def wire_schema_for(self, request, validation_schema, evidence):
        if self._product_support_wire:
            return product_wire_schema(validation_schema, evidence)
        return super().wire_schema_for(request, validation_schema, evidence)

    def decode_wire_payload(self, request, payload, evidence):
        if self._product_support_wire:
            return decode_product_wire(payload, evidence)
        return super().decode_wire_payload(request, payload, evidence)

    def provider_schema_for(self, request, validation_schema):
        collapsed = 0
        if self._minimal_provider_schema:
            provider_schema = minimal_positioning_schema()
        elif self._provider_schema_projection and single_support_anyof_count(validation_schema):
            try:
                provider_schema = collapse_single_support_anyof(validation_schema)
            except SchemaProjectionError:
                log.warning("POSITIONING schema projection rejected execution_id=%s code=equivalence_unproved",
                            request.execution_id)
                raise
            collapsed = single_support_anyof_count(validation_schema) - single_support_anyof_count(provider_schema)
        else:
            provider_schema = super().provider_schema_for(request, validation_schema)
        provider_schema = positioning_observation_schema(
            provider_schema, minimal=self._minimal_provider_schema)
        original = schema_measurement(validation_schema)
        provider = schema_measurement(provider_schema)
        fields = {"module_id": self.module_id.value, "execution_id": request.execution_id,
            "minimal_provider_schema_enabled": self._minimal_provider_schema,
            "schema_projection_enabled": self._provider_schema_projection,
            "schema_projection_applied": collapsed > 0, "schema_projection_nodes": collapsed,
            "validation_schema_bytes": original["bytes"], "validation_schema_sha256": original["sha256"],
            "provider_schema_bytes": provider["bytes"], "provider_schema_sha256": provider["sha256"]}
        if self._product_support_wire:
            fields["wire_contract_version"] = WIRE_VERSION
            fields["wire_schema_bytes"] = fields.pop("validation_schema_bytes")
            fields["wire_schema_sha256"] = fields.pop("validation_schema_sha256")
        log.info("POSITIONING provider schema " + " ".join(f"{key}=%s" for key in fields),
                 *fields.values(), extra=fields)
        return provider_schema

    def output_budget_for(self, request):
        # Preparation has checked the requested names. Only the complete
        # server-owned contract gets extra headroom, independent of user text.
        if set(request.expected_outputs) == set(ModuleRegistry.load("1.1.0").get(self.module_id).outputs):
            return ModuleOutputBudget.POSITIONING_FULL
        return ModuleOutputBudget.GENERIC

    def output_type_for(self, request, evidence):
        supplied = {item.input_key for item in evidence}
        return {
            (True, True): PositioningOutput,
            (False, True): PositioningWithoutJobOutput,
            (True, False): PositioningWithoutAlternativeOutput,
            (False, False): PositioningWithoutSeedsOutput,
        }[("customer_job_or_need" in supplied, "relevant_alternative" in supplied)]

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
        output_type = type(output)
        limit = output_type.model_json_schema()["properties"]["limitations"]["maxItems"]
        combined = list(dict.fromkeys((*limitations, *output.limitations)))[:limit]
        output = output_type.model_validate({**output.model_dump(), "limitations": combined})
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
                raise StatementSemanticsError(SemanticRule.MISSING_SEED_REQUIRES_HYPOTHESIS)
        if statement.output_name in ("differentiation", "points_of_difference", "USP_directions") and statement.kind != "HYPOTHESIS":
            raise StatementSemanticsError(SemanticRule.DIFFERENTIATION_REQUIRES_HYPOTHESIS)
        if statement.output_name in PRODUCT_OUTPUTS:
            if not any(local[e].input_key in PRODUCT_CATEGORIES for e in statement.evidence_ids):
                raise StatementSemanticsError(SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH)
        require_supported_numbers(statement.text, supported_text(statement, local, parents))
        if statement.kind == "OBSERVATION":
            # Preserve numeric authority separately: only factual parents can
            # authorize an observation, and only their assertion channel counts.
            factual = [pid for pid in statement.parent_claim_ids
                       if parents[pid].claim_type in (ClaimType.OBSERVATION, ClaimType.FACT)]
            observed = statement.model_copy(update={"parent_claim_ids": factual})
            if not any(statement.text in source for source in supported_text(observed, local, parents)):
                raise StatementSemanticsError(SemanticRule.OBSERVATION_SUPPORT_REQUIRED)
