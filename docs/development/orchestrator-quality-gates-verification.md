# Orchestrator Quality Gates verification

Status: reconciled runtime foundation implemented and verified on `agent/add-orchestrator-quality-gates` without execution-path integration.

## Identity and ownership

- Authoritative base: `607696ab02da7dafabfcdd0bfeb2f29724b80c38`.
- Runtime owner: `app/marketing_orchestrator/quality_gates/`.
- Public internal entry points: `QualityGateEvaluator.evaluate` and `DecisionEvaluator.evaluate`.
- Boundary: pure, immutable, deterministic and always `PLANNING_ONLY`.
- Migrations/dependencies: none.

## Focused evidence

| Evidence | Result |
| --- | --- |
| Quality Gates contracts, canonicalization, total iterative lineage, evaluator propagation, contradictions, decisions, manifest, hostile boundary, fingerprint evidence and isolation | 179 passed; one pre-existing Pydantic warning |
| Module Registry | 27 passed |
| Marketing Orchestrator compatibility | 117 passed; four pre-existing Pydantic warnings |
| Expert Core, integration, Agent Registry and TaskPipeline compatibility | 43 passed |
| Historical baseline before initial apply | 269 passed; nine pre-existing warnings |
| Current full suite | 448 passed; nine pre-existing warnings |

Current focused tests prove controlled construction for every public caller-owned contract; exact closed-enum membership; one propagated context per claim; iterative one-parent, multi-parent, multi-level and diamond lineage; cycle rejection; confidence ceilings; decision-trigger retention; propagated decision/manifest source sets; hostile rejection; and an independently declared caller fingerprint field matrix whose every baseline and mutation successfully passes production evaluation before fingerprint comparison.

## Canonical vectors

- Empty-contradiction fixture fingerprint: `20c9fb5190f14cfdbf629821ed4a3a48a257a4960c6b9d3cb1ca8d42beb9a33b`.
- Two-side contradiction fixture fingerprint: `578850d498e6d6e28673e7bd8274138af3266a713bb3d2148d9363189e64ff99`.
- Limitation vector: `lim_2b42fd3a91882bc24469ecfa3334aed0`.
- Exclusion vector: `exc_a2e97bf393be35ca457a154117ceb728`.

Tests cover RFC 8785 UTF-16 key ordering and escaping, typed integers/floats, signed zero, UTC offset normalization, every contradiction-side key, and order-significant side reversal. Fingerprints contain caller inputs only and no derived cycle.

The independent matrix names every caller-owned batch, result, claim, evidence, assumption, limitation, contradiction and side field. It uses separate evaluator-valid `PASS`, `PASS_WITH_LIMITATIONS`, `FAIL`, `BLOCKED`, lineage, contradiction, multi-result and multi-record fixture families rather than an overloaded batch. Accepted fixtures contain no failure/blocking reasons; reason fields use their legal failed/blocked states; and the only handoff fixtures use Registry-confirmed `VIRTUAL_CMO` handoffs (`POSITIONING` and `EXPERIMENTS`).

Ordinary leaves declare exact expected constructed-tree paths; the catalog validator calculates actual paths and requires exact equality plus agreement with the normative source label. `batch_id`, `result_id`, `claim_id`, `evidence_id`, `assumption_id`, `limitation_id` and `contradiction_id` retain independently declared minimal reference closures that are compared with actual before/after data. Gate-coherent coupled evidence is declared separately for status/materiality combinations. Deterministic mutation signatures contain independently normalized caller trees, actual changed paths and values, and raw order evidence where applicable; no case name, source label or category participates in signature identity.

Results, claims, evidence, assumptions, limitations and contradictions use stable record identities to prove exactly one complete element is added or removed while retained content remains equal. `contradiction.left` and `.right` structural coverage is resolved from the actual isolated descendant mutation paths, with one real case per descendant. Every normalization and side-position case retains a pre-normalization raw witness: one shared builder consumes the baseline sequence and its exact reverse, while catalog validation proves two or more distinct elements, equal membership, no unrelated raw change and correspondence between witnessed and supplied contracts. Twelve negative controls exercise that same validator and reject a mislabelled leaf, duplicate actual mutation, identity rename disguised as membership, missing structural descendant, identical/short/duplicate/non-reversed/membership-changing raw sequences, unrelated raw changes, an unused witness and fake legacy element-count metadata.

All 67 declared pairs validate both batches through `QualityGateEvaluator`, check `PLANNING_ONLY`, and only then execute their expected fingerprint comparison. Derived `batch_fingerprint`, propagated contexts, aggregates and other output-only fields remain excluded.

## Propagation and decision evidence

- `PropagatedClaimContext` is frozen/slotted, output-only, batch-identified, and emitted exactly once per claim in claim-ID order.
- Evaluator propagation uses a lexical ready-heap Kahn traversal over parent-to-child edges. It calculates each context after every parent, rejects any unprocessed cyclic remainder, and contains no recursion or depth limit.
- Direct 1,100-claim regressions cover forward/reverse ID chains, reordered cross-result input, multiple roots, forward/reverse long cycles, and a long chain ending in a short cycle. Valid chains preserve lexical outputs, records, conservative confidence, immutability and repeated-evaluation equality; cycles raise only `QualityGateContractError`.
- Evidence, assumptions, material and non-material limitations recursively union by stable ID; diamond paths deduplicate and unequal duplicate batch identities fail deterministically.
- Effective confidence never exceeds the most conservative effective parent; repeated equal evaluation is idempotent and caller records are unchanged.
- Owning `GateDecision` values merge declared and effective IDs without unrelated records or duplicates. Effective material limitations produce `PASS_WITH_LIMITATIONS` and accepted-result propagated limitations enter the manifest.
- Decision precedence changes only `decision`; all validated replan and stop reasons remain in their corresponding lexical tuples, including mixed terminal/replan/lower-stop requests.

## Contradiction and derived-output evidence

- `ContradictionSide` contains exactly claim/evidence IDs plus complete object, segment, period and metric-definition keys.
- Selected evidence references and claim membership are validated before comparability.
- Each key mismatch independently produces `INCOMPARABLE`; precedence freshness is not called afterward.
- Fully comparable first-party evidence is prioritized only over a not-newer generic benchmark.
- Unresolved/incomparable claims remain preserved, are excluded, and receive one material derived limitation per affected result.
- Side reversal changes fingerprint while preserving state and preferred claim.
- Fixed length-prefixed ID vectors, deterministic ordering and injected collision failure are covered.
- Decisions cover blocked, failed, terminal-stop, replan, lower-stop and continue outcomes.
- Manifest tests prove evaluated/accepted/excluded sets are resolved, exhaustive and disjoint.

## Hostile and error boundary

Dedicated tests reject hostile subclasses of string, integer, float, list, tuple, dict, set and frozenset plus custom `Mapping`, `Sequence`, `Set`, datetime subclass, nested values and mapping proxies before hostile iteration, equality, length, lookup, copying, representation, formatting, hashing, containment, numeric conversion or reduction. Controlled binding converts missing, unknown, conflicting and output-only arguments to `QualityGateContractError`; valid construction and immutability remain intact. Expected public Registry errors are converted to `QualityGateContractError`; `BaseException` and programmer defects are not caught.

## Registry and isolation

- Registry version: `1.0.0`.
- Descriptors: 15.
- Execution bindings: 0.
- Normalized checksum: `25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918`.
- Spy call counts: OpenAI/LLM 0, `QCService` 0, `TaskPipelineService` 0, persistence 0.
- Import-boundary tests prohibit LLM, QC, agents, presenters, routers, Telegram, SQLAlchemy, Redis, workflow and execution-service dependencies.
- Existing planner/validator, agents, presenters, public DTOs, `AgentRegistry`, `TaskPipelineService`, API and Telegram paths do not import Quality Gates and remain unchanged in the branch diff.
- Outputs contain no plan, prose, raw module dump, chain-of-thought field or public response DTO.

## Current implementation checks

Full pytest passed with 448 tests and the same nine pre-existing warnings. Python compilation for `app` and `bot` passed. Strict change/all validation and final branch diff checks passed. Historical runtime commit `af28b9273d881e6e8ff89b62930fe36bbf401388` remains the pre-reconciliation implementation reference only.

## Remaining limitations

Adapters from existing heterogeneous agent dictionaries, workflow integration, persistence and user-facing synthesis remain separate reviewed changes. Evidence independence and semantic authority inference remain intentionally deferred. These are intentional product boundaries, not blockers for this planning-only foundation.
