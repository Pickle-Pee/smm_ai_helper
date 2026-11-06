"""Traceable experiment design, without campaign execution or invented forecasts."""
from dataclasses import replace
import json

from app.marketing_orchestrator.quality_gates.contracts import (
    BlockingReason, ClaimType, Confidence, EvidenceRecord, EvidenceSourceClass,
)
from app.module_registry import ModuleId, ModuleRegistry
from app.model_generation_policy import ModuleOutputBudget

from .common import (
    LocalEvidence, ExecutorOutputError, OutputFailureStage, ResultContractError, ResultFailureRule,
    blocked, first_party_evidence, log, normalize_result, parent_claims,
    scoped_facts, stable_id, plain,
)
from .provider_schema import (
    schema_measurement, SchemaProjectionError,
    collapse_redundant_support_anyof, collapse_single_support_anyof,
)
from .support_schema import SupportRequirement
from .experiments_support_wire import WIRE_VERSION, strategic_parent_wire_schema, decode_strategic_parent_wire
from .experiments_support_selection import (
    WIRE_VERSION as SELECTION_WIRE_VERSION, support_selection_catalog,
    support_selection_wire_schema, decode_support_selection_wire,
)
from .schema_annotations import strip_schema_annotations
from .intelligence_common import IntelligenceExecutor, require_supported_numbers
from .intelligence_schemas import ExperimentsOutput
from .claim_support import assertion_support
from .downstream_fidelity import FIDELITY_INSTRUCTION


def strategic_parents(request):
    eligible = {c.claim_id for u in request.upstream_results
                if u.module_id in (ModuleId.VIRTUAL_CMO, ModuleId.POSITIONING)
                for c in u.result.normalized_result.claims
                if c.claim_type is ClaimType.HYPOTHESIS}
    return {key: claim for key, claim in parent_claims(request).items() if key in eligible}


def experiment_constraint_evidence(evidence):
    return tuple(e for e in evidence if e.input_key in (
        "constraints", "time_resource_constraint", "budget", "duration"))


class ExperimentsExecutor(IntelligenceExecutor):
    module_id = ModuleId.EXPERIMENTS
    executor_key = "experiments.v1"
    schema_version = "experiments.payload.v1"
    output_type = ExperimentsOutput
    instruction = """Turn accepted strategic/positioning hypotheses into falsifiable experiment designs.
Do not execute campaigns. Each experiment must cite existing material HYPOTHESIS
claims from VIRTUAL_CMO or POSITIONING. Every canonical output must cite such a parent.
Specify hypothesis, observable primary metric, intervention, expected directional
signal, failure/falsification condition and minimum inputs. Preserve supplied time
and resource constraints; otherwise time_resource_constraints is empty. Expected
changes are hypotheses, never forecasted facts. Do not invent uplift, budget,
duration, sample size, MDE or significance thresholds. Numerical text must be copied
verbatim from cited supplied statements, never calculated or invented. Keep new
canonical statements and design fields qualitative, without digits or numbered
lists, even when context contains numbers. A numeric assertion is allowed only
when the entire statement or field is copied verbatim from its cited support.
Quantities written as words are numbers too. Do not invent counts of questions,
visits, participants or other units in interventions or minimum required inputs;
keep unsupplied quantities qualitative rather than spelling out invented numbers.
Preserve supplied numeric constraints verbatim in time_resource_constraints;
do not weave their numbers into newly composed assertions. Structured
VIRTUAL_CMO parents supply qualitative summaries/actions only. Their numeric_context
quotes are attributed context, never numerical support for outputs or design fields.
Use HYPOTHESIS or RECOMMENDATION kinds. Formal AB designs without baseline,
measurement/population data stay limited and state required inputs.
Keep control/treatment, guardrails, stop/scale decisions, inconclusive outcomes and
learning_record explicit in requested canonical outputs. At most three experiments.
Treat minimum_required_inputs as separate text leaves, not labels exempt from
source rules. If an input refers to an existing demonstration, use its COMPLETE
verbatim existing_proof sentence as the entire item, and select that local source
on the first canonical output, which supplies nested-design evidence. Do not
wrap it in 'access to', 'already existing', parentheses or a relative clause.
Other minimum inputs describe information or access still to obtain. Do not
present an unprovided current landing page, campaign or service format as fact.
A comparison sample does not illustrate written-feedback delivery merely because
the course also includes written feedback. Test message emphasis without making
that unsupported connection, and request owner confirmation of the format.""" + FIDELITY_INSTRUCTION
    limitation = "Experiment designs are hypotheses, not forecasts; missing baseline, population, economics and resource inputs prevent formal sizing or causal conclusions."

    def __init__(self, *, model_call, composer=None, provider_schema_projection=False,
                 strategic_parent_wire=False, support_selection_wire=False):
        if type(provider_schema_projection) is not bool:
            raise TypeError("Expected boolean EXPERIMENTS projection policy")
        if type(strategic_parent_wire) is not bool:
            raise TypeError("Expected boolean EXPERIMENTS strategic parent wire policy")
        if type(support_selection_wire) is not bool:
            raise TypeError("Expected boolean EXPERIMENTS support selection wire policy")
        if support_selection_wire and not strategic_parent_wire:
            raise ValueError("EXPERIMENTS support selection requires strategic parent wire")
        super().__init__(model_call=model_call, composer=composer)
        self._support_selection_wire = support_selection_wire
        if support_selection_wire:
            self.instruction += f"\nUse wire_contract_version {SELECTION_WIRE_VERSION}. " + """Keep strategic_parent_id as an explicit eligible strategic source ID. Omit evidence_ids
and parent_claim_ids arrays. Use experiments_support_selection_catalog aliases in
additional_evidence_support and additional_parent_support; every required key must
be boolean. True selects support; false does not exclude the mandatory strategic
parent. Primary UNION additional true choices defines the canonical citation set.
Select no more than thirty-two distinct sources per family in total. Cite sources
actually supporting numerical text; a text or numeric assertion does not add a
citation. When evidence_basis is requested, the server makes it the first
canonical output regardless of generated array order. Partial requests without
it retain the first generated output as the nested-source owner. Select each
local owner/demo source needed by nested design leaves on that owner; a selection
on another output cannot repair it.
Keep all original grounding, design and exact constraint requirements."""
        self._provider_schema_projection = provider_schema_projection
        self._strategic_parent_wire = strategic_parent_wire

    def support_requirement_for(self, request):
        # Every accepted output already requires an eligible strategic parent
        # in build_result. Express the nonempty part before model execution.
        return SupportRequirement.PARENT_REQUIRED

    def model_input_for(self, request, data, evidence, parents):
        if self._support_selection_wire:
            return {**data, "experiments_support_selection_catalog": support_selection_catalog(
                (e.record.evidence_id for e in evidence), parents)}
        return data

    def wire_schema_for(self, request, validation_schema, evidence):
        wire = self._v2_wire_schema(request, validation_schema, evidence)
        if self._support_selection_wire:
            parents = parent_claims(request)
            choices = support_selection_catalog((e.record.evidence_id for e in evidence), parents)
            count = len(request.expected_outputs) * sum(map(len, choices.values()))
            log.info("EXPERIMENTS support selection schema output_count=%d evidence_choice_count=%d parent_choice_count=%d required_boolean_flags=%d",
                len(request.expected_outputs), len(choices["evidence"]), len(choices["parents"]), count)
            return support_selection_wire_schema(wire, len(request.expected_outputs),
                (e.record.evidence_id for e in evidence), parents)
        return wire

    def _v2_wire_schema(self, request, validation_schema, evidence):
        if self._strategic_parent_wire:
            eligible = strategic_parents(request)
            return strategic_parent_wire_schema(validation_schema, eligible,
                tuple(str(e.value) for e in experiment_constraint_evidence(evidence)),
                strategic_assertions=tuple(text for claim in eligible.values()
                    for text in assertion_support(claim.value)),
                statement_assertions=tuple(e.value if isinstance(e.value, str)
                    else json.dumps(plain(e.value), ensure_ascii=False) for e in evidence) + tuple(
                    text for claim in parent_claims(request).values()
                    for text in assertion_support(claim.value)))
        return validation_schema

    def decode_wire_payload(self, request, payload, evidence):
        if self._support_selection_wire:
            from .support_schema import support_response_schema
            parents = parent_claims(request)
            evidence_ids = tuple(e.record.evidence_id for e in evidence)
            canonical = support_response_schema(self.output_type_for(request, evidence), evidence_ids,
                parents, requirement=self.support_requirement_for(request))
            return decode_support_selection_wire(payload, self._v2_wire_schema(request, canonical, evidence),
                len(request.expected_outputs), evidence_ids, parents)
        return decode_strategic_parent_wire(payload, strategic_parents(request))

    def provider_schema_for(self, request, validation_schema):
        try:
            if self._provider_schema_projection:
                simplified = collapse_redundant_support_anyof(validation_schema)
                simplified = collapse_single_support_anyof(simplified)
                provider_schema, removed = strip_schema_annotations(simplified)
            else:
                provider_schema = super().provider_schema_for(request, validation_schema)
                removed = 0
            original = schema_measurement(validation_schema)
            provider = schema_measurement(provider_schema)
        except (SchemaProjectionError, TypeError, ValueError, RecursionError):
            log.warning("EXPERIMENTS schema projection rejected code=equivalence_unproved")
            raise SchemaProjectionError("annotation_projection_not_equivalent") from None
        fields = {"strategic_parent_wire_enabled": self._strategic_parent_wire,
            "support_selection_wire_enabled": self._support_selection_wire,
            "schema_contract_version": (SELECTION_WIRE_VERSION if self._support_selection_wire
                else WIRE_VERSION if self._strategic_parent_wire else self.schema_version),
            "schema_projection_enabled": self._provider_schema_projection,
            "schema_projection_applied": provider_schema != validation_schema,
            "schema_projection_annotations_removed": removed,
            "validation_schema_bytes": original["bytes"], "validation_schema_sha256": original["sha256"],
            "provider_schema_bytes": provider["bytes"], "provider_schema_sha256": provider["sha256"]}
        log.info("EXPERIMENTS provider schema " + " ".join(f"{key}=%s" for key in fields),
                 *fields.values(), extra=fields)
        return provider_schema

    def output_budget_for(self, request) -> ModuleOutputBudget:
        # Only the complete server-owned output contract receives extra headroom.
        if set(request.expected_outputs) == set(ModuleRegistry.load("1.3.0").get(self.module_id).outputs):
            return ModuleOutputBudget.EXPERIMENTS_FULL
        return ModuleOutputBudget.GENERIC

    async def execute(self, request):
        early = self.prepare(request)
        if early is not None:
            return early
        if not strategic_parents(request):
            return blocked(request, self.schema_version, BlockingReason.MISSING_BLOCKING_INPUT,
                           "Accepted material VIRTUAL_CMO/POSITIONING hypothesis required")
        evidence = first_party_evidence(request, scoped_facts(request)) + tuple(
            LocalEvidence(EvidenceRecord(stable_id("evd", request, "constraint", str(i)),
                EvidenceSourceClass.FIRST_PARTY, "Caller-supplied scoped constraint"),
                value, Confidence.MEDIUM, "constraints")
            for i, value in enumerate(request.context_packet.constraints))
        return await self.generate(request, evidence)

    def build_result(self, request, output, evidence, parents):
        from .downstream_fidelity import comparison_quotes, selected_sources, text_leaves, validate_leaf, validate_limitation

        local = {item.record.evidence_id: item for item in evidence}
        for statement in output.outputs:
            owner, demo = selected_sources(statement, local)
            validate_leaf(statement.text, owner=owner, demo=demo,
                          comparisons=comparison_quotes(request, statement),
                          copy_field=statement.output_name in {"control", "treatment"})
        # Structured designs are persisted in the first claim. Only that claim's
        # explicit local selections can witness their product/demo assertions;
        # another output's quote and strategic HYP parents cannot repair them.
        design_owner, design_demo = selected_sources(output.outputs[0], local) if output.outputs else ((), ())
        design_comparisons = comparison_quotes(request, output.outputs[0]) if output.outputs else ()
        for experiment in output.experiments:
            for text in text_leaves(experiment.model_dump()):
                validate_leaf(text, owner=design_owner, demo=design_demo, comparisons=design_comparisons)
        for text in output.assumptions:
            validate_leaf(text)
        for text in output.limitations:
            validate_limitation(text, local)
        eligible = strategic_parents(request)
        for output_index, statement in enumerate(output.outputs):
            # Reject before the first output's design/constraint union. That
            # normalization must never repair duplicated model citations.
            if (len(statement.evidence_ids) != len(set(statement.evidence_ids))
                    or len(statement.parent_claim_ids) != len(set(statement.parent_claim_ids))):
                raise ExecutorOutputError(stage=OutputFailureStage.SUPPORT_IDENTITY_INVALID)
            if not set(statement.parent_claim_ids) & eligible.keys():
                raise ResultContractError(ResultFailureRule.OUTPUT_MISSING_STRATEGIC_PARENT, output_index=output_index)
        for experiment_index, experiment in enumerate(output.experiments):
            refs = experiment.related_strategic_claim_ids
            if len(refs) != len(set(refs)):
                raise ResultContractError(ResultFailureRule.EXPERIMENT_DUPLICATE_STRATEGIC_REFERENCES,
                                          experiment_index=experiment_index)
            if not set(refs) <= eligible.keys():
                raise ResultContractError(ResultFailureRule.EXPERIMENT_INVALID_STRATEGIC_REFERENCES,
                                          experiment_index=experiment_index)
            supports = tuple(text for p in refs for text in assertion_support(eligible[p].value))
            for key, value in experiment.model_dump().items():
                if key in ("related_strategic_claim_ids", "time_resource_constraints"):
                    continue
                for text in value if isinstance(value, list) else [value]:
                    require_supported_numbers(text, supports)
            constraints = experiment_constraint_evidence(evidence)
            if (len(experiment.time_resource_constraints) != len(set(experiment.time_resource_constraints))
                    or set(experiment.time_resource_constraints) != {str(e.value) for e in constraints}):
                raise ResultContractError(ResultFailureRule.EXPERIMENT_CONSTRAINTS_MISMATCH, experiment_index=experiment_index)
            output.outputs[0].evidence_ids = list(dict.fromkeys((
                *output.outputs[0].evidence_ids, *(e.record.evidence_id for e in constraints))))
            # Attach the complete structured design to the first normalized claim;
            # union its parents so the confidence ceiling covers every experiment.
            output.outputs[0].parent_claim_ids = list(dict.fromkeys((*output.outputs[0].parent_claim_ids, *refs)))
        result = super().build_result(request, output, evidence, parents)
        first, *rest = result.normalized_result.claims
        first = normalize_result(replace, first, output_index=0, value=json.dumps({"summary": first.value,
            "experiments": [e.model_dump() for e in output.experiments]}, ensure_ascii=False))
        return normalize_result(replace, result, payload=output.model_dump(mode="json"),
                       normalized_result=normalize_result(replace, result.normalized_result, claims=(first, *rest)))

    def validate_statement(self, statement, local, parents):
        super().validate_statement(statement, local, parents)
        if statement.kind not in ("HYPOTHESIS", "RECOMMENDATION"):
            raise ResultContractError(ResultFailureRule.OUTPUT_INVALID_KIND,
                                      stage=OutputFailureStage.STATEMENT_SEMANTICS_INVALID)
