# Orchestrator Quality Gates product contract

## Planned responsibility

Quality Gates are a planned pure, deterministic, immutable and `PLANNING_ONLY` internal boundary over caller-supplied typed normalized results. Runtime ownership will be `app/marketing_orchestrator/quality_gates/`. The boundary derives structural validity, gate outcome, readiness, decisions and synthesis eligibility; callers cannot assert those states.

It does not execute modules, call an LLM or model-based `QCService`, query/persist context, create Jobs, use Redis/workers, orchestrate workflows, generate/revise plans, expose APIs/Telegram behavior, interpret arbitrary prose or synthesize user-facing text.

## Canonical vocabulary

- Claim: `FACT`, `OBSERVATION`, `INFERENCE`, `HYPOTHESIS`, `ASSUMPTION`, `FORECAST`, `RECOMMENDATION`.
- Confidence: `UNKNOWN < LOW < MEDIUM < HIGH`; no normalized-result float confidence.
- Evidence sufficiency: `SUFFICIENT`, `LIMITED`, `INSUFFICIENT`, `NOT_ASSESSED`.
- Module status and separate derived gate outcome: `PASS`, `PASS_WITH_LIMITATIONS`, `FAIL`, `BLOCKED`.
- Lineage: `ORIGINAL`, `REPEATS`, `REFORMULATES`, `DERIVES`.
- Contradiction: `UNRESOLVED`, `PRIORITIZED`, `INCOMPARABLE`.
- Decision: `CONTINUE_CURRENT_PLAN`, `REPLAN_REQUIRED`, `STOP`, `BLOCKED`.

All remaining authority, materiality, limitation, failure, blocking, exclusion, replan, stop, source-class, freshness and precedence vocabularies are closed enums defined in the OpenSpec design; strings are not converted into enum values.

## Identity and time

Every entity uses an exact lowercase ASCII prefixed ID (`bat_`, `res_`, `clm_`, `evd_`, `asm_`, `lim_`, `ctr_`, `exc_`) with no trimming or normalization. There is no manifest/decision ID. A schema-tagged RFC 8785 tree with typed scalar nodes produces the SHA-256 fingerprint; every derived output, including separate derived limitations and the batch aggregate, carries both batch values.

Each contradiction has immutable caller-supplied `left` and `right` sides. A side contains its claim ID, optional explicitly selected evidence ID, and complete typed `object_key`, `segment_key`, `period_key` and `metric_definition_key` scope metadata. Quality Gates never infer these keys from claim/evidence text, module output or Registry prose. All four pairs are compared exactly before evidence: any mismatch deterministically yields `INCOMPARABLE`, preserves and excludes both claims from unqualified synthesis, and creates a material limitation per affected result. Side order is preserved in the fingerprint, so reversal changes batch identity while preserving semantic state/preferred claim.

Evidence time accepts only exact aware `datetime`, normalizes explicit offsets to UTC, preserves microseconds and serializes with `Z`. Evaluation uses no ambient clock or timezone. Missing timestamps remain incomparable.

## Gate policy

- `PASS`: usable claim, sufficient evidence, no material limitation/reasons, permitted authority.
- `PASS_WITH_LIMITATIONS`: usable claim, sufficient/limited evidence and at least one material limitation.
- `FAIL`: structurally valid unusable result with typed failure reason and no synthesis eligibility.
- `BLOCKED`: typed blocker, `NOT_ASSESSED`, no claim and no synthesis eligibility.
- Every other combination raises `QualityGateContractError` in deterministic phase/field order.
- Registry `1.0.0` keeps zero bindings, so readiness is always derived `PLANNING_ONLY`.

## Propagation and contradictions

Only explicit resolved acyclic lineage IDs propagate. Each claim receives an output-only aggregate context containing recursive evidence, assumption, material/non-material limitation IDs and conservative effective confidence. Identical stable IDs deduplicate, unequal content collides, and all sets are lexically ordered. Owning result decisions expose these effective IDs; accepted-result propagated limitations also reach the manifest. Repetition/reformulation/derivation never exceeds the most conservative effective parent confidence; `UNKNOWN` remains `UNKNOWN`. New evidence is preserved but cannot increase confidence; evidence independence remains deferred.

Contradictions compare exact keys using only one caller-selected evidence record per side, validated as belonging to that claim. The evaluator never selects or aggregates evidence. First-party may be prioritized only over selected generic-benchmark evidence with equal/newer explicit time, using `FIRST_PARTY_NOT_OLDER_THAN_BENCHMARK`; every other case is unresolved/incomparable.

Unresolved/incomparable claims stay preserved but receive typed exclusions and per-result derived limitations. In prioritized contradictions, the non-preferred claim receives `CONTRADICTION_PRECEDENCE` without a limitation. Any claim exclusion prevents unqualified acceptance; preference elsewhere cannot override it.

## Decisions and synthesis eligibility

`BLOCKED` gates produce only matching `BLOCKED`; `FAIL` produces only `STOP/RESULT_FAILED`. For accepted gates, completion/sufficient evidence stops first, material finding/dependency invalidation/reversible-test value replans second, diminishing/tool/capability limits stop third, and no trigger continues. Precedence chooses only the final decision; all validated stop and replan reasons remain visible in their corresponding ordered output tuples. Decisions never execute work.

The batch aggregate exposes decisions, one propagated context per claim, contradiction records, actual derived limitations, exclusions and the manifest. Manifest source sets include complete decision limitations from accepted results only and contradiction claim exclusions only for accepted results; failed/blocked results use one result exclusion. It generates no prose, raw dumps, hidden reasoning or public DTO.

Every public caller-owned contract has a controlled construction boundary: missing, unknown, conflicting, or output-only arguments fail as `QualityGateContractError`, while exact valid positional/keyword construction and deep immutability remain supported.

## Compatibility

Registry validates only canonical identity, exact declared-output membership and registered handoffs; it supplies no module-specific required schema or executable adapter. Existing heterogeneous agents, presenters, public DTOs, planner/validator, `AgentRegistry`, `QCService` and `TaskPipelineService` remain unchanged. Future adapters and workflow/synthesis integration require separate changes.

`docs/product/prompts/orchestrator-production.md` remains product source material only and is not loaded or copied into runtime code.
