"""Traceable experiment design, without campaign execution or invented forecasts."""
from dataclasses import replace
import json

from app.marketing_orchestrator.quality_gates.contracts import (
    BlockingReason, ClaimType, Confidence, EvidenceRecord, EvidenceSourceClass,
)
from app.module_registry import ModuleId, ModuleRegistry
from app.model_generation_policy import ModuleOutputBudget

from .common import (
    LocalEvidence, OutputFailureStage, ResultContractError, ResultFailureRule,
    blocked, first_party_evidence, log, normalize_result, parent_claims,
    scoped_facts, stable_id,
)
from .provider_schema import schema_measurement, SchemaProjectionError
from .schema_annotations import strip_schema_annotations
from .intelligence_common import IntelligenceExecutor, require_supported_numbers
from .intelligence_schemas import ExperimentsOutput
from .claim_support import assertion_support


def strategic_parents(request):
    eligible = {c.claim_id for u in request.upstream_results
                if u.module_id in (ModuleId.VIRTUAL_CMO, ModuleId.POSITIONING)
                for c in u.result.normalized_result.claims
                if c.claim_type is ClaimType.HYPOTHESIS}
    return {key: claim for key, claim in parent_claims(request).items() if key in eligible}


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
verbatim from cited supplied statements, never calculated or invented. Structured
VIRTUAL_CMO parents supply qualitative summaries/actions only. Their numeric_context
quotes are attributed context, never numerical support for outputs or design fields.
Use HYPOTHESIS or RECOMMENDATION kinds. Formal AB designs without baseline,
measurement/population data stay limited and state required inputs.
Keep control/treatment, guardrails, stop/scale decisions, inconclusive outcomes and
learning_record explicit in requested canonical outputs. At most three experiments."""
    limitation = "Experiment designs are hypotheses, not forecasts; missing baseline, population, economics and resource inputs prevent formal sizing or causal conclusions."

    def __init__(self, *, model_call, composer=None, provider_schema_projection=False):
        if type(provider_schema_projection) is not bool:
            raise TypeError("Expected boolean EXPERIMENTS projection policy")
        super().__init__(model_call=model_call, composer=composer)
        self._provider_schema_projection = provider_schema_projection

    def provider_schema_for(self, request, validation_schema):
        try:
            if self._provider_schema_projection:
                provider_schema, removed = strip_schema_annotations(validation_schema)
            else:
                provider_schema = super().provider_schema_for(request, validation_schema)
                removed = 0
            original = schema_measurement(validation_schema)
            provider = schema_measurement(provider_schema)
        except (SchemaProjectionError, TypeError, ValueError, RecursionError):
            log.warning("EXPERIMENTS schema projection rejected code=equivalence_unproved")
            raise SchemaProjectionError("annotation_projection_not_equivalent") from None
        fields = {"schema_projection_enabled": self._provider_schema_projection,
            "schema_projection_applied": removed > 0, "schema_projection_annotations_removed": removed,
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
        eligible = strategic_parents(request)
        for output_index, statement in enumerate(output.outputs):
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
            constraints = tuple(e for e in evidence if e.input_key in (
                "constraints", "time_resource_constraint", "budget", "duration"))
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
