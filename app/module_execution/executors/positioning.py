"""Positioning from explicit product truth and optional predecessor results."""
from app.marketing_orchestrator.quality_gates.contracts import BlockingReason, ClaimType
from app.module_registry import ModuleId, ModuleRegistry
from app.model_generation_policy import ModuleOutputBudget

from .common import (
    BaseExecutor, SemanticRule, StatementSemanticsError, blocked, facts_for,
    first_party_evidence, scoped_facts, parent_claims, log,
)
from .provider_schema import (
    SchemaProjectionError, collapse_single_support_anyof, single_support_anyof_count, schema_measurement,
)
from .positioning_provider_schema import minimal_positioning_schema
from .positioning_observation_schema import positioning_observation_schema
from .positioning_assurance import (
    ASSURANCE as _ASSURANCE, NO_EQUIPMENT_PURCHASE, has_product_assurance,
    supports_no_equipment_purchase,
)
from .intelligence_common import require_supported_numbers, supported_text
from .claim_support import assertion_support
from .schemas import (
    PositioningOutput, PositioningWithoutAlternativeOutput, PositioningWithoutJobOutput,
    PositioningWithoutSeedsOutput,
)
from .positioning_support_selection import (
    support_selection_wire_schema, decode_support_selection_wire, support_selection_catalog,
    product_source_catalog, source_assertion_aliases,
    WIRE_VERSION as SELECTION_WIRE_VERSION,
)
from .support_schema import support_response_schema
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
truth/proof; a positioning statement is not a slogan.
Use target only for who the audience is and what it wants to achieve. Describe
audience characteristics and needs using audience evidence, and keep uncertainty
explicit. Keep all product conditions out of target, including equipment
requirements or exemptions, delivery format, included items, eligibility and
terms of use. This applies even when the condition is sourced or phrased as
something the audience wants. Put supported product conditions in a requested
product output such as value_proposition or offer. If no suitable product output
was requested, omit the condition. Do not infer product features or terms from
the audience profile or product name.
Never invent uniqueness or
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
Quantities written as words are numbers too: never invent counts of visits,
questions, participants or other units; use an entire verbatim supported statement.
Across every requested output, including offer, USP_directions and message_hierarchy,
do not introduce one/single or один/одна/одно/одну as stylistic determiners before
counted units. Prefer unquantified format wording: "вводное занятие" rather than
"одно вводное занятие", and "посещение" rather than "одно посещение". Correct
fulfillment conditions do not authorize an unsupplied count. A quantity is allowed
only when the WHOLE statement is copied verbatim from its actually cited support.
Before returning, self-check every statement for counts in digits or words; choose
unquantified wording during generation when the count is not supplied, preserving
all supplied fulfillment conditions.
Preserve supplied fulfillment conditions, including postprocessing and delayed
collection. Do not turn them into promises of completion in a single visit,
immediate delivery or no further actions. New operational promises require owner
confirmation and must not be asserted as an offer.
RTB is supplied substantiation, not a new inference or promotional promise. Its
entire text must be a verbatim contiguous quotation from one actually cited local
product_truth or existing_proof source. Copy the source wording without adding
conclusions such as no further actions, guaranteed convenience or proven results.
Do not paraphrase or strengthen the proof. Supplied owner statements are not
independent verification; retain that limitation instead of inventing evidence.
Across ALL outputs, do not add guarantees or qualifications to supplied facts:
"with a master" does not mean an experienced, qualified, professional or certified
master; a finished product after firing does not establish a guarantee. Avoid
guarantee/qualification words (гарантия, опытный, квалифицированный,
профессиональный, сертифицированный, безусловный; guarantee, experienced,
qualified, professional, certified, unconditional) unless the WHOLE statement is
copied verbatim from actually cited local product_truth/existing_proof. This also
applies to hypotheses and recommendations; discuss risks with neutral wording
instead. Preserve delayed collection in product messages. Do not strengthen the
owner's statements when writing slogans or message hierarchies.
Observations must quote one actually cited local source or accepted factual parent
verbatim; an upstream hypothesis is not observed evidence. Use HYPOTHESIS or
INFERENCE for unsupported reasoning. Provider generation permits INFERENCE,
HYPOTHESIS and RECOMMENDATION only, subject to the stricter output-specific kinds."""
    limitation = "Positioning uses supplied product truth and optional predecessor claims; uniqueness and customer response require validation."

    def __init__(self, *, model_call, composer=None, provider_schema_projection=False,
                 product_support_wire=False, minimal_provider_schema=False, support_selection_wire=False):
        if type(support_selection_wire) is not bool:
            raise TypeError("Expected boolean POSITIONING support selection policy")
        if support_selection_wire and (product_support_wire or minimal_provider_schema):
            raise ValueError("POSITIONING support selection requires other wire experiments disabled")
        self._support_selection_wire = support_selection_wire
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

        if support_selection_wire:
            self.instruction += f"\nUse wire_contract_version {SELECTION_WIRE_VERSION}." + """
Return outputs as an object keyed by exactly the requested output names. Do not
emit evidence_ids/parent_claim_ids arrays. Use positioning_support_selection_catalog
aliases: select primary_support_key for each output except RTB and set every closed
boolean evidence_support/parent_support flag explicitly. True means the source
is materially used, false means unused. Product outputs require primary local
product truth/proof; other outputs may use accepted parents or local evidence.
For target, use the audience source as primary when used. Write audience-only
QUALITATIVE prose, or use SOURCE for an exact audience-only assertion. Do not
select or quote a product condition for target in either mode.
Primary and true additional overlap denotes one citation. Retain all original
source authority, numeric, RTB, assurance, kind and fulfillment conditions.
Free text must stay qualitative, use unqualified roles and end with punctuation.
For outputs other than RTB, text is an explicit object: {"mode":"QUALITATIVE","value":"..."} for
new qualitative prose, or {"mode":"SOURCE","value":"..."} for an ENTIRE
AllowedPositioningSupportedAssertion. For a product fact, select its key from
positioning_product_sources, using only keys whose allowed_outputs lists that
output. The server renders the entire supplied assertion with its evidence.
The product_truth catalog supplies verbatim context for strategic reasoning.
existing_proof keys are RTB material only; never infer product conditions from
them. Use a product key in offer and RTB for the exact factual terms. In
value_proposition, positioning_statement and message_hierarchy, write a benefit
hypothesis, positioning recommendation and message angle respectively, each
with a distinct purpose. Ground the angle in the source without repeating the
offer. Express it as something to test or communicate. Treat delivery format,
assignment details, feedback arrangements, equipment, instructor qualifications
and outcomes as unknown unless explicitly supported. Preserve all limits and
conditions of any source you use. Describe unknowns as questions to verify. Never return a bare text string. Other SOURCE values still require
explicit support selection.
The qualitative pattern excludes ASCII digits. Keep prose unquantified and roles
unqualified; do not invent or respell counts or add guarantees/qualifications.
Any supplied numerical fact or qualification must use an ENTIRE exact source
assertion and its actual cited source, never an invented or paraphrased fact.
Use QUALITATIVE for neutral prose only. If a product output needs a supplied
condition expressed with qualification wording (including negated equipment
requirements), use SOURCE with the corresponding positioning_product_sources
key. Use the same mechanism for factual product attributes such as the delivery
format, assignments and feedback. Do not infer a recurring practice from an
example, a homework requirement from a task, or personal feedback from written
feedback. Treat unverified competitive differences as hypotheses to validate. Keep mixed summaries
neutral and leave the qualified condition in the separate sourced output. If
there is no suitable exact assertion or requested slot, omit the qualified claim.
For claim_risks, describe the uncertainty neutrally, for example
"Уточнить, что именно получает участник после курса." Avoid quoting or negating
qualification terms in free-text risk descriptions.
Supplied assertions are literal alternatives; their existence alone is not evidence. If ANY quantity is needed, including a supplied
duration, use its product source key or an ENTIRE exact non-product source
assertion with its actual citation. Never paraphrase a numerical fact, respell digits in
words (six weeks / шесть недель), shorten or combine source sentences. Otherwise
omit the quantity from that free-form statement. For RTB, use SOURCE mode and set
text.value to a key from positioning_product_sources and the AllowedPositioningRTBSourceKey
enum. That key supplies the entire verbatim text and its required citation together.
Use the support flags only for additional sources that materially support the RTB.
RTB cannot use QUALITATIVE mode or paraphrase proof;
other positioning/offer text can stay useful without repeating its duration.
The numeric enum is an explicit generation alternative, not independent evidence;
every numerical statement still requires its actually selected cited source."""

    def model_input_for(self, request, data, evidence, parents):
        if self._support_selection_wire:
            context = data["context"]
            data = {**data, "context": {
                **context, "known_facts": [
                    fact for fact in context["known_facts"]
                    if (fact.get("input_key") or fact.get("label")) not in PRODUCT_CATEGORIES
                ],
            }, "local_evidence": [
                {key: value for key, value in row.items() if key != "value"}
                if row["input_key"] in PRODUCT_CATEGORIES else row
                for row in data["local_evidence"]
            ], "positioning_support_selection_catalog": support_selection_catalog(
                (e.record.evidence_id for e in evidence), parents)}
            product_sources = product_source_catalog(evidence)
            if product_sources:
                data["positioning_product_sources"] = {
                    key: {field: value for field, value in source.items()
                          if field != "text" or source["category"] == "product_truth"}
                    for key, source in product_sources.items()
                }
            aliases = source_assertion_aliases(evidence, (
                text for claim in parents.values() for text in assertion_support(claim.value)))
            product_literals = {source["text"] for source in product_sources.values()}
            aliases = {key: value for key, value in aliases.items() if value not in product_literals}
            if aliases:
                data["positioning_source_assertions"] = {
                    "usage": "For a quoted SOURCE assertion, select its key from the schema enum. "
                             "The key represents the entire mapped text and requires its actual citation.",
                    "values": aliases,
                }
        return data

    def wire_schema_for(self, request, validation_schema, evidence):
        if self._support_selection_wire:
            parents = parent_claims(request)
            choices = support_selection_catalog((e.record.evidence_id for e in evidence), parents)
            log.info("POSITIONING support selection outputs=%d evidence_choices=%d parent_choices=%d required_boolean_flags=%d",
                len(request.expected_outputs), len(choices["evidence"]), len(choices["parents"]),
                len(request.expected_outputs) * sum(map(len, choices.values())))
            return support_selection_wire_schema(validation_schema, self.output_type_for(request, evidence),
                request.expected_outputs, evidence, parents, parent_assertions=tuple(
                    text for claim in parents.values() for text in assertion_support(claim.value)))
        if self._product_support_wire:
            return product_wire_schema(validation_schema, evidence)
        return super().wire_schema_for(request, validation_schema, evidence)

    def decode_wire_payload(self, request, payload, evidence):
        if self._support_selection_wire:
            parents = parent_claims(request)
            output_type = self.output_type_for(request, evidence)
            canonical = support_response_schema(output_type, (e.record.evidence_id for e in evidence), parents)
            return decode_support_selection_wire(payload, canonical, output_type,
                request.expected_outputs, evidence, parents, parent_assertions=tuple(
                    text for claim in parents.values() for text in assertion_support(claim.value)))
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
        if statement.output_name == "RTB" or has_product_assurance(statement.text):
            proof = statement.model_copy(update={
                "evidence_ids": [e for e in statement.evidence_ids if local[e].input_key in PRODUCT_CATEGORIES],
                "parent_claim_ids": [],
            })
            if not any(statement.text in source for source in supported_text(proof, local, parents)):
                rule = (SemanticRule.RTB_QUOTE_REQUIRED if statement.output_name == "RTB"
                        else SemanticRule.PRODUCT_ASSURANCE_SUPPORT_REQUIRED)
                raise StatementSemanticsError(rule)
        if statement.output_name != "RTB" and NO_EQUIPMENT_PURCHASE.search(statement.text) and not any(
            local[e].input_key in PRODUCT_CATEGORIES and isinstance(local[e].value, str)
            and (statement.text in local[e].value or supports_no_equipment_purchase(local[e].value))
            for e in statement.evidence_ids
        ):
            raise StatementSemanticsError(SemanticRule.PRODUCT_CLAIM_REQUIRES_TRUTH)
        if statement.kind == "OBSERVATION":
            # Preserve numeric authority separately: only factual parents can
            # authorize an observation, and only their assertion channel counts.
            factual = [pid for pid in statement.parent_claim_ids
                       if parents[pid].claim_type in (ClaimType.OBSERVATION, ClaimType.FACT)]
            observed = statement.model_copy(update={"parent_claim_ids": factual})
            if not any(statement.text in source for source in supported_text(observed, local, parents)):
                raise StatementSemanticsError(SemanticRule.OBSERVATION_SUPPORT_REQUIRED)
