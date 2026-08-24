# Design: Orchestrator quality gates

## Gate scope

Quality gates проверяют contract-level properties:

- module status valid;
- required output fields present;
- evidence references structurally valid;
- assumptions/confidence represented;
- limitations not dropped;
- declared authority respected where this can be checked by output type;
- handoff points to registered module;
- blocked/fail results not promoted to confident success.

Они не определяют автоматически, истинно ли содержательное утверждение.

## Status rules

- `PASS`: required contract satisfied without material unresolved limitation.
- `PASS_WITH_LIMITATIONS`: useful result with material uncertainty/coverage limitation.
- `FAIL`: module could not provide usable output.
- `BLOCKED`: execution cannot proceed without blocking input or capability.

## Propagation

Downstream packets inherit claim type, evidence provenance, confidence and limitations. Confidence cannot increase solely because a downstream module repeats or reformulates a claim.

## Contradictions

Conflicting claims are represented explicitly. The system checks whether object, segment, period, metric definition and source differ before choosing precedence. First-party current evidence normally outranks generic benchmark, but no conflict is silently averaged.

## Replanning

After a major validated finding, the orchestrator asks whether the highest-value next step changed. Replanning produces a new validated plan version without rewriting prior findings or decisions.

## Synthesis

User output is built from accepted results and clearly marked limitations. Internal module names and routing trace are not exposed unless useful for explainability. Hidden chain-of-thought is never returned.

## Tests

Deterministic unit tests cover contracts and transitions. Model-based evals, if added, run separately from deterministic CI unless explicitly stabilized.

