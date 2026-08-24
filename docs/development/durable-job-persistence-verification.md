# Durable Job persistence verification

Status: pre-implementation evidence template. Nothing in this document claims that the Job runtime, migration, or tests exist or pass.

## Identification

- OpenSpec change: `add-durable-job-persistence`
- Planning base: `bcdbd509450dd9d391ef7eeebf34134887264838`
- Planned branch: `agent/add-durable-job-persistence`
- Planned migration parent: `20260814_0003`
- Planned migration revision: re-check the single head during apply; design proposes `20260825_0004`
- Implementation commit: pending
- Implementation PR: pending

## Contract evidence to record after implementation

| Area | Required evidence | Result |
| --- | --- | --- |
| Model/table | Exact columns, SQL/Python types, nullability, defaults, server defaults, mutability, limits | Pending |
| Enum | Exact `pending`, `running`, `succeeded`, `failed` membership and no synonyms | Pending |
| Ownership | Exclusive optional run/user/system ownership and step-requires-run rejection | Pending |
| Foreign keys | User `SET NULL`, MarketingRun `CASCADE`, relationship compatibility | Pending |
| Constraints/indexes | Every named check and exact index; no extra uniqueness | Pending |
| JSON | Object-only payload/result, JSON-compatible deep copy, empty-object policy | Pending |
| Lifecycle | Every legal transition and every illegal edge/same/terminal transition | Pending |
| Coherence | State-specific result/error/start/completion requirements | Pending |
| Time | Aware UTC normalization, microseconds, created/updated/start/completion ordering | Pending |
| Service queries | Get/missing behavior and deterministic run listing | Pending |
| Transactions | Flush/no commit/no rollback, caller rollback, atomic MarketingRun relationship | Pending |
| Concurrency | `SELECT ... FOR UPDATE` and post-lock state evaluation | Pending |
| Persistence errors | Duplicate/FK/check failure propagation and rollback ownership | Pending |
| Migration | Head continuity, upgrade, reflected schema, downgrade, re-upgrade | Pending |
| Compatibility | MarketingRun/Artifact, API/Telegram, pipeline, Orchestrator, Quality Gates, Registry | Pending |
| Isolation | Zero Redis/worker/queue/polling/execution/LLM/QC/API/Telegram calls | Pending |
| Packaging | No dependency, Docker, CI, or lock-file impact | Pending |

## Module Registry compatibility snapshot to re-verify

- Version: expected `1.0.0`
- Descriptor count: expected 15
- Execution bindings: expected 0
- Normalized JSON SHA-256: expected `25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918`
- Actual after implementation: pending

## Commands to execute after implementation

Do not mark any command complete until it actually exits successfully.

- [ ] Focused Job model/service tests.
- [ ] PostgreSQL migration upgrade from `20260814_0003`.
- [ ] Reflected schema/constraint/index verification.
- [ ] PostgreSQL downgrade one revision and re-upgrade.
- [ ] `.venv\Scripts\python.exe -m pytest -q`
- [ ] `.venv\Scripts\python.exe -m compileall app bot`
- [ ] `.venv\Scripts\python.exe -m alembic heads`
- [ ] `openspec validate add-durable-job-persistence --strict`
- [ ] `openspec validate --all --strict`
- [ ] `git diff --check origin/sale-ready...HEAD`

## Compatibility evidence to record after implementation

- Existing API/public DTO and Telegram diff: pending.
- `TaskPipelineService` and standalone task regressions: pending.
- MarketingRun/MarketingArtifact regression results: pending.
- Marketing Orchestrator/Quality Gates regression results: pending.
- Module Registry version/count/bindings/checksum: pending.
- LLM/OpenAI call delta: pending.
- QC call delta: pending.
- Redis/queue/worker calls and configuration delta: pending.
- Dependency manifest, Docker, and CI delta: pending.

## Limitations to carry into implementation report

- A committed pending Job is durable but inert; publication/claim/execution is absent.
- Retry, idempotency, cancellation, timeout, ordering, delivery, leases, and dead-letter behavior are absent.
- PostgreSQL and a future Redis publication are not atomic; no outbox is approved here.
- Supported executable Job kinds remain undefined until a later producer/worker contract.
