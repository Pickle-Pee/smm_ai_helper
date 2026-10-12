# EXPERIMENTS result rejection diagnostics

Reported replay: `req_06d7388ca87640c180cd187eb4b0bd27`, HTTP 200,
`completed`, 2437 output tokens. Initial JSON Schema and Pydantic passed,
then `ExecutorOutputError.stage=result_contract_invalid`. Original schema hash:
`49c9d21c942a1c5dd97af086fc1189e8d2f78ebd294edc58a1546b0e55560150`;
provider schema hash:
`27e6f30e45dd5aa10a5d5ee83a1e4529ec483e863f8d8c497c8cb80022582d68`.
These facts do not identify the rejecting server check. No response text was
available or retained, and no live replay was performed for this change.

Production graph worker -> dispatcher -> ExperimentsExecutor.execute ->
BaseExecutor.generate -> production_model_call -> one HTTP POST /responses.
Provider success is followed by original request-scoped JSON Schema and initial
Pydantic validation. Result construction then runs, in this order:

1. ExperimentsExecutor.build_result checks every output's eligible strategic
   parent, then each experiment's references, numeric grounding and constraints.
   It unions design parents and constraint evidence into the first output.
2. IntelligenceExecutor.build_result revalidates the mutated payload with
   Pydantic, then rejects duplicate output names.
3. BaseExecutor.build_result checks output coverage, duplicate support identities,
   local evidence and accepted parent allowlists, support presence and statement
   semantics. It clamps confidence and constructs the normalized contracts.
4. ExperimentsExecutor attaches structured designs to the first normalized claim
   and constructs the final result. Quality Gates subsequently own acceptance.

Accepted upstream results and scoped facts remain the authoritative sources of
support. Eligibility requires in-scope accepted VIRTUAL_CMO/POSITIONING hypotheses.
This change adds diagnostics, not a second validator or a repair path. Persisted
job state, failure stages, retries, payload version and acceptance rules do not
change; no migration is required. ResultContractError remains an ExecutorOutputError.

| failure_rule | Actual rejecting check | Safe position |
| --- | --- | --- |
| output_missing_strategic_parent | Output parents do not intersect eligible strategic hypotheses | output_index |
| experiment_duplicate_strategic_references | Experiment references contain duplicates (checked first) | experiment_index |
| experiment_invalid_strategic_references | Experiment references are not a subset of eligible hypotheses | experiment_index |
| experiment_constraints_mismatch | Constraints contain duplicates or differ from supplied constraints | experiment_index |
| post_mutation_pydantic_invalid | Real Pydantic ValidationError on revalidation after support mutation | none |
| output_duplicate_names | Revalidated output names contain duplicates | first duplicate output_index |
| output_invalid_kind | EXPERIMENTS kind restriction rejects after Intelligence semantics | output_index |
| result_normalization_invalid | A normalized claim/result/assumption/limitation constructor or final dataclass replacement rejects | output_index when constructing a claim |
| other_result_contract_invalid | Otherwise unclassified caught failure while building the result | none |

Positions are zero-based. Only enum-selected codes and exact nonnegative integer
positions enter diagnostic logs/errors. No text, support identity, constraint
value, Pydantic input, exception message or traceback is logged. The generation
boundary replaces the exception and suppresses exception chaining. The fallback
means an unclassified check failed; it does not infer the model's mistake.
Earlier JSON/schema, coverage, provenance and numerical/statement failures retain
their existing stages and diagnostics. First actual rejection wins.

## Schema/runtime kind mismatch (unchanged)

ExperimentStatement inherits OutputStatement's four JSON Schema/Pydantic kinds:
OBSERVATION, INFERENCE, HYPOTHESIS, RECOMMENDATION. ExperimentsExecutor's runtime
check permits only HYPOTHESIS and RECOMMENDATION. OBSERVATION first needs to quote
supplied support to pass the earlier Intelligence check; unsupported observations
fail there before the EXPERIMENTS kind check. The kind check retains the historical
`statement_semantics_invalid` stage, now with `failure_rule=output_invalid_kind`.
Consequently a reported `result_contract_invalid` does not establish that this
restriction caused the incident. Do not narrow the schema or widen runtime without
incident evidence and a separately reviewed contract change.

## Verification and next authorized replay

The isolated [verification recipe](../runbooks/verify-experiments-projection.md)
returns safe `failure_rule` and available positions even on result-contract
failure. It retains explicit approval, original instruction/input/schema
fingerprints, checks the reported projected schema fingerprint, compares the
entire provider wire, permits one HTTP call, closes read-only restoration before
I/O and performs no database writes. It disables logging, never prints exceptions,
and stops without retries. Schema hashes are pinned to this incident; instruction
and input fingerprints still require private operator approval. A successful
synthetic offline test does not authorize live use or global rollout.

Offline tests cover every cause, actual parent-union overflow after initially
valid wire, constructor rejection, check precedence, safe logging, runbook failure
summaries, fingerprint refusal, all four kinds and unchanged full provider wire
with either projection policy. Existing executor and schema suites cover the
unchanged fail-closed checks. Full CI includes Python integration tests and the
container-smoke workflow using disabled external providers.
