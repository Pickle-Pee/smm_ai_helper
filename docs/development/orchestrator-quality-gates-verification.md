# Orchestrator Quality Gates verification

Status: runtime foundation implemented and verified on `agent/add-orchestrator-quality-gates` without execution-path integration.

## Identity and ownership

- Authoritative base: `607696ab02da7dafabfcdd0bfeb2f29724b80c38`.
- Runtime owner: `app/marketing_orchestrator/quality_gates/`.
- Public internal entry points: `QualityGateEvaluator.evaluate` and `DecisionEvaluator.evaluate`.
- Boundary: pure, immutable, deterministic and always `PLANNING_ONLY`.
- Migrations/dependencies: none.

## Focused evidence

| Evidence | Result |
| --- | --- |
| Quality Gates contracts, canonicalization, evaluator, propagation, contradictions, decisions, manifest, hostile boundary and isolation | 60 passed; one pre-existing Pydantic warning |
| Module Registry | 27 passed |
| Marketing Orchestrator compatibility | 117 passed; four pre-existing Pydantic warnings |
| Expert Core, integration, Agent Registry and TaskPipeline compatibility | 43 passed |
| Baseline before apply | 269 passed; nine pre-existing warnings |
| Full suite after apply | 329 passed; nine pre-existing warnings |

Focused tests prove exact closed enums and field shapes, defensive freezing, prefixed IDs, caller/output ownership, legal/illegal gate states, parent-confidence ceilings, stable identity unions, all contradiction states, decision precedence, exhaustive manifest accounting and closed internal exports.

## Canonical vectors

- Empty-contradiction fixture fingerprint: `20c9fb5190f14cfdbf629821ed4a3a48a257a4960c6b9d3cb1ca8d42beb9a33b`.
- Two-side contradiction fixture fingerprint: `578850d498e6d6e28673e7bd8274138af3266a713bb3d2148d9363189e64ff99`.
- Limitation vector: `lim_2b42fd3a91882bc24469ecfa3334aed0`.
- Exclusion vector: `exc_a2e97bf393be35ca457a154117ceb728`.

Tests cover RFC 8785 UTF-16 key ordering and escaping, typed integers/floats, signed zero, UTC offset normalization, every contradiction-side key, and order-significant side reversal. Fingerprints contain caller inputs only and no derived cycle.

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

Dedicated tests reject hostile list, tuple, set, dict, string, datetime subclass and mapping-proxy inputs before hostile iteration, hashing, formatting or backing access. Wrong nested items are type-checked before hashing. Expected Registry errors are converted to `QualityGateContractError`; `BaseException` and programmer defects are not caught.

## Registry and isolation

- Registry version: `1.0.0`.
- Descriptors: 15.
- Execution bindings: 0.
- Normalized checksum: `25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918`.
- Spy call counts: OpenAI/LLM 0, `QCService` 0, `TaskPipelineService` 0, persistence 0.
- Import-boundary tests prohibit LLM, QC, agents, presenters, routers, Telegram, SQLAlchemy, Redis, workflow and execution-service dependencies.
- Existing planner/validator, agents, presenters, public DTOs, `AgentRegistry`, `TaskPipelineService`, API and Telegram paths do not import Quality Gates and remain unchanged in the branch diff.
- Outputs contain no plan, prose, raw module dump, chain-of-thought field or public response DTO.

## Final checks

Full pytest passed with 329 tests and the same nine pre-existing warnings. Python compilation for `app` and `bot`, strict change validation, strict all-OpenSpec validation (11 items), and both branch/working-tree diff checks passed. There is no configured lint/type tool, Docker/dependency change, or manual runtime integration step because the package is intentionally unused by current execution paths.

## Remaining limitations

Adapters from existing heterogeneous agent dictionaries, workflow integration, persistence and user-facing synthesis remain separate reviewed changes. Evidence independence and semantic authority inference remain intentionally deferred.
