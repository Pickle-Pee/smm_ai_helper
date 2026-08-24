# Orchestrator Quality Gates product contract

## Responsibility

Quality Gates are a deterministic, planning-only decision boundary for already-typed normalized module results. They answer whether a supplied result is structurally legal and eligible for later downstream use. They do not execute work or judge whether arbitrary marketing prose is true or strategically good.

## Inputs and outputs

The boundary accepts immutable normalized results with stable result, claim, evidence, assumption and limitation IDs; canonical Registry module IDs; explicit claim types and provenance; finite confidence; materiality; typed failure/blocking reasons; and optional registered handoffs.

It returns immutable gate, contradiction, next-step, stop and synthesis-eligibility decisions. Module status, structural validity, gate outcome, evidence sufficiency, confidence, limitations, contradiction state, execution readiness and synthesis eligibility remain separate.

Malformed contracts raise a dedicated error. A valid `FAIL` means the caller explicitly supplied a structurally complete but unusable result. A valid `BLOCKED` means a typed missing input/capability prevents use. Neither substitutes for missing required fields.

## Deterministic policy

- `PASS`: accepted claims, sufficient evidence metadata and no material limitation.
- `PASS_WITH_LIMITATIONS`: usable claims plus at least one preserved material limitation.
- `FAIL`: typed failure reason and no accepted downstream claims.
- `BLOCKED`: typed missing blocking input/capability and no accepted downstream claims.
- Contract completeness never proves claim truth, causality, ethics, evidence independence or strategic quality.
- Repetition never raises confidence. New evidence is preserved, but confidence does not increase in this foundation because independence cannot be verified.
- Assumptions never become facts and material limitations are never dropped.
- Contradictions are typed inputs, never discovered by reading prose. Both claims remain present and are never averaged.
- Explicitly current first-party evidence may outrank an explicitly generic benchmark only for matching typed comparison dimensions; missing freshness, incomparable fields and ties remain unresolved.
- Replanning/stopping decisions use only explicit triggers and never mutate or execute plans.

## Synthesis boundary

This foundation may produce a manifest containing accepted result/claim IDs, limitations, unresolved contradictions and typed exclusions. It does not produce user-facing prose, raw module dumps, hidden reasoning or a public response wrapper. Actual synthesis and delivery require a later workflow integration change.

## Runtime compatibility

`QCService` remains the existing model-based editorial check and is not called. Existing agents and presenters retain their heterogeneous dictionaries; future explicit adapters are required. `TaskPipelineService`, APIs, Telegram, persistence, Jobs, Redis and workers are unchanged. Module Registry `1.0.0` remains metadata-only with zero execution bindings and every Marketing Orchestrator plan remains `PLANNING_ONLY`.

Registry metadata supports identity, declared-output membership and registered-handoff checks. It does not specify invocation-specific required result schemas, so module-specific completeness and semantic authority checks are deferred.

## Source ownership

This document and the active OpenSpec change define the product/engineering contract. `docs/product/prompts/orchestrator-production.md` is product source material only; it is not loaded by this deterministic foundation and is not duplicated into Python.
