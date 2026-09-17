"""Traceable experiment design, without campaign execution or invented forecasts."""
from dataclasses import replace
import json

from app.marketing_orchestrator.quality_gates.contracts import (
    BlockingReason, ClaimType, Confidence, EvidenceRecord, EvidenceSourceClass,
)
from app.module_registry import ModuleId

from .common import LocalEvidence, blocked, first_party_evidence, parent_claims, scoped_facts, stable_id
from .intelligence_common import IntelligenceExecutor, require_supported_numbers
from .intelligence_schemas import ExperimentsOutput


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
verbatim from cited supplied statements, never calculated or invented.
Use HYPOTHESIS or RECOMMENDATION kinds. Formal AB designs without baseline,
measurement/population data stay limited and state required inputs.
Keep control/treatment, guardrails, stop/scale decisions, inconclusive outcomes and
learning_record explicit in requested canonical outputs. At most three experiments."""
    limitation = "Experiment designs are hypotheses, not forecasts; missing baseline, population, economics and resource inputs prevent formal sizing or causal conclusions."

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
        for statement in output.outputs:
            if not set(statement.parent_claim_ids) & eligible.keys():
                raise ValueError("Every experiment output must reference a strategic hypothesis")
        for experiment in output.experiments:
            refs = experiment.related_strategic_claim_ids
            if len(refs) != len(set(refs)) or not set(refs) <= eligible.keys():
                raise ValueError("Experiment requires existing material strategic hypotheses")
            supports = tuple(str(eligible[p].value) for p in refs)
            for key, value in experiment.model_dump().items():
                if key in ("related_strategic_claim_ids", "time_resource_constraints"):
                    continue
                for text in value if isinstance(value, list) else [value]:
                    require_supported_numbers(text, supports)
            constraints = tuple(e for e in evidence if e.input_key in (
                "constraints", "time_resource_constraint", "budget", "duration"))
            if (len(experiment.time_resource_constraints) != len(set(experiment.time_resource_constraints))
                    or set(experiment.time_resource_constraints) != {str(e.value) for e in constraints}):
                raise ValueError("Preserve every supplied time/resource constraint verbatim")
            output.outputs[0].evidence_ids = list(dict.fromkeys((
                *output.outputs[0].evidence_ids, *(e.record.evidence_id for e in constraints))))
            # Attach the complete structured design to the first normalized claim;
            # union its parents so the confidence ceiling covers every experiment.
            output.outputs[0].parent_claim_ids = list(dict.fromkeys((*output.outputs[0].parent_claim_ids, *refs)))
        result = super().build_result(request, output, evidence, parents)
        first, *rest = result.normalized_result.claims
        first = replace(first, value=json.dumps({"summary": first.value,
            "experiments": [e.model_dump() for e in output.experiments]}, ensure_ascii=False))
        return replace(result, payload=output.model_dump(mode="json"),
                       normalized_result=replace(result.normalized_result, claims=(first, *rest)))

    def validate_statement(self, statement, local, parents):
        super().validate_statement(statement, local, parents)
        if statement.kind not in ("HYPOTHESIS", "RECOMMENDATION"):
            raise ValueError("Expected changes cannot be forecasted facts")
