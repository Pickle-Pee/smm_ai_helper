# Durable Job persistence verification

Status: runtime implementation complete with local/static evidence. Disposable PostgreSQL execution evidence is pending because no safe database target was available.

## Identification

- OpenSpec change: `add-durable-job-persistence`
- Planning base: `bcdbd509450dd9d391ef7eeebf34134887264838`
- Planned branch: `agent/add-durable-job-persistence`
- Migration parent: `20260814_0003`
- Migration revision and sole metadata head: `20260825_0004`
- Final task accounting: 262 total; 221 checked; 41 PostgreSQL-dependent evidence tasks pending
- Implementation commit: recorded in the final delivery report after commit creation
- Implementation PR: not created; branch push is the authorized delivery boundary

## Contract evidence to record after implementation

| Area | Required evidence | Result |
| --- | --- | --- |
| Model/table | Exact fourteen columns, SQL/Python types, nullability/defaults, service-managed `version`, and absent fields | Passed: static model/migration assertions |
| Enum | Exact ordered `pending`, `running`, `succeeded`, `failed`; raw-string boundary rejection | Passed |
| Ownership | Run/direct-user/system creation, invalid dual owner/step, owner lookup, four ORM relationships | Passed locally; unloaded PostgreSQL cascade pending |
| Foreign keys/deletion | Exact `CASCADE` metadata; loaded ORM deletion and delete-orphan | Static/local passed; PostgreSQL FK execution pending |
| Immutability | Pre-SQL protected/relationship/collection/deletion rejection; rollback; untracked JSON reload; unrelated state preservation | Passed with real SQLAlchemy identity-map unit harness |
| Identifier/kind | UUID hex generation/supply, run ID, key boundaries, exact types, no normalization | Passed |
| JSON domain | Exact recursive types, int64, finite floats, Unicode/U+0000, cycles, depth 16, canonical options | Passed |
| JSON limits | Payload 262,144 bytes and result 1,048,576 bytes, including one-byte-over rejection | Passed |
| Error safety | Exact sanitized string, Unicode, ASCII whitespace, 4000-character limit, no stringification | Python passed; PostgreSQL whitespace constraint pending |
| Constraints | Exact eleven names/predicates in model and migration | Static passed; PostgreSQL acceptance/rejection pending |
| Indexes | Exact run/status composites only | Static passed; PostgreSQL reflection pending |
| Lifecycle | All legal and illegal edges with exact fields and `0 -> 1 -> 2` increments | Passed locally |
| Version | Exact expected-version type/range, stale/exhausted/illegal precedence, single success increment | Passed locally |
| Time | One injected clock, aware UTC normalization/microseconds, exact equalities/order rejection | Passed locally |
| Service precedence | ID through database failure, including dirty/missing/stale/exhausted/illegal order | Passed locally |
| Queries | Malformed/missing lookup and deterministic run listing; no extra query surfaces | Passed locally |
| Transactions | Scoped add/flush; no commit/rollback/refresh; unrelated unit-of-work state preserved | Passed locally; PostgreSQL atomicity pending |
| Concurrency | Gated row-lock/version contention, terminal competition, sequential-version tests | Added; not executed without disposable PostgreSQL |
| Migration | Revision/parent/operations and sole metadata head | Static/head passed; upgrade/downgrade/re-upgrade pending |
| Compatibility | MarketingRun/Artifact, API/Telegram, pipeline, Orchestrator, Quality Gates, Registry | Passed: focused 377-test run and full suite |
| Isolation | No Redis/worker/LLM/QC/API/Telegram/external integration or transaction ownership expansion | Passed: AST/source evidence |
| Packaging | No manifest, dependency, Docker, Compose, CI, environment, or lock-file changes | Passed by diff audit |

## Exact database predicate checklist

All predicates below passed static model/migration assertions. Their direct PostgreSQL acceptance/rejection checks remain pending.

- [ ] `ck_jobs_job_id_format`: exact lowercase UUID-hex regex.
- [ ] `ck_jobs_kind_format`: exact canonical-key regex.
- [ ] `ck_jobs_workflow_step_format`: null or exact canonical-key regex.
- [ ] `ck_jobs_exclusive_owner`: `marketing_run_id IS NULL OR user_id IS NULL`.
- [ ] `ck_jobs_step_requires_run`: `workflow_step IS NULL OR marketing_run_id IS NOT NULL`.
- [ ] `ck_jobs_status`: exact four-value vocabulary.
- [ ] `ck_jobs_version_nonnegative`: `version >= 0`.
- [ ] `ck_jobs_payload_object`: exact JSON object.
- [ ] `ck_jobs_result_object`: null or exact JSON object.
- [ ] `ck_jobs_lifecycle`: exact four-state outcome/time predicate, including matching ASCII-whitespace error rule.
- [ ] `ck_jobs_timestamp_order`: exact creation/start/completion ordering and update equalities.

The normative SQL text is in `openspec/changes/add-durable-job-persistence/design.md`; evidence records reflected expressions and direct PostgreSQL accepted/rejected rows separately for every item.

## Security evidence

- System Job creation exists only on the unused internal persistence service; no current caller exists: passed source audit.
- No public/Telegram anonymous or system-owner switch exists: passed source audit and full regression.
- Producer redaction remains an upstream obligation; no runtime producer was added: passed scope audit.
- Persistence performs no automatic secret detection: confirmed by service source/import audit.
- Failed transitions accept only a sanitized exact string and reject exception/custom objects: passed.
- Stable errors contain no raw payload/result/error value: passed taxonomy/message assertions.

## Module Registry compatibility snapshot to re-verify

- Version: expected `1.0.0`
- Descriptor count: expected 15
- Execution bindings: expected 0
- Normalized JSON SHA-256: expected `25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918`
- Actual after implementation: version `1.0.0`; 15 descriptors; zero bindings; expected SHA-256; 27 focused tests passed.

## Commands to execute after implementation

Do not mark any command complete until it actually exits successfully.

- [x] Focused Job model/default/relationship tests: included in `137 passed, 13 skipped` focused Job run.
- [x] Focused validators/service/lifecycle/immutability tests: included in the same run; service file independently reports `125 passed`.
- [ ] Focused PostgreSQL constraint/transaction/concurrency tests.
- [ ] PostgreSQL migration upgrade from `20260814_0003`.
- [ ] PostgreSQL downgrade one revision.
- [ ] PostgreSQL deterministic re-upgrade.
- [x] `.venv\Scripts\python.exe -m pytest -q`: `596 passed, 13 skipped, 22 warnings`.
- [x] `.venv\Scripts\python.exe -m compileall app bot`: passed.
- [x] `.venv\Scripts\python.exe -m alembic heads`: `20260825_0004 (head)`.
- [x] `openspec validate add-durable-job-persistence --strict`: valid.
- [x] `openspec validate --all --strict`: 12 passed, 0 failed.
- [x] `git diff --check`: passed before commit; repeated during final audit.
- [x] `git status --short`: only approved task paths before commit; clean after commit/push.
- [x] Prohibited-path/dependency/Docker/CI audit: passed; preserved `.idea` stash excluded.

## Compatibility evidence

- MarketingRun and MarketingArtifact behavior: focused compatibility run passed.
- `TaskPipelineService`, TaskRouter, AgentRunner, and AgentRegistry behavior/call counts: focused compatibility run passed.
- Marketing Orchestrator and Quality Gates remain deterministic and `PLANNING_ONLY`: focused compatibility run passed.
- Module Registry identity: exact focused 27-test run passed.
- Public API/schemas/presenters and Telegram handlers: full regression passed; source audit found no Job surface.
- Redis, worker/queue/polling/scheduler, LLM/OpenAI, model-based QC, URL/image/provider calls: AST/import audit found none in Job persistence.
- Persistence commit/rollback/refresh: AST call audit and session fakes found none.
- Dependency manifests, Docker, Compose, CI, environment, and lock/package resources: unchanged in the diff.

## PostgreSQL evidence blocker and manual command

No `DURABLE_JOB_TEST_DATABASE_URL` was configured, localhost PostgreSQL was unavailable, and the Docker daemon was not running. The configured Compose database uses persistent `smm_db_data`, so it was not treated as disposable. The 13 PostgreSQL tests therefore skipped without touching a database.

To complete the remaining evidence safely, supply a disposable PostgreSQL URL whose database name contains `durable_job_test`, then run:

```powershell
$env:DURABLE_JOB_TEST_DATABASE_URL = "postgresql+asyncpg://<user>:<password>@<host>/<durable_job_test_database>"
.venv\Scripts\python.exe -m pytest -q tests/test_job_postgresql.py
```

The module-scoped fixture records/restores the starting known revision and refuses database names without the disposable marker. Do not point it at a development, shared, staging, or production database.

## Implementation inventory and transaction evidence

- Model: `app/models.py` adds `JobStatus`, `Job`, and the two aggregate collection relationships.
- Service: `app/services/job_persistence_service.py` adds the four approved methods and nine-class safe domain taxonomy.
- Migration: `migrations/versions/20260825_0004_durable_job_persistence.py`, revision `20260825_0004`, parent `20260814_0003`.
- Tests: static model/migration, validator/service/identity-map, isolation, and gated PostgreSQL suites under `tests/test_job_*.py`.
- Reconciled artifacts: design, delta spec, product contract, verification evidence, and tasks for the maximum-version rule.
- Transaction boundary: create adds and scoped-flushes once; transition locks/reloads and scoped-flushes once; reads do not flush; service AST has no commit, rollback, refresh, or expiration calls. Database failures pass through for caller rollback.
- Packaging impact: none; requirements, lock/package resources, Dockerfile, Compose, CI, environment, configuration, API, Telegram, Redis, workers, LLM/QC, and execution integration are unchanged.

## Limitations to carry into implementation report

- Jobs are operational aggregate records, not retained audit history; deleting a run/user deletes its owned Jobs.
- Supported transitions reject tracked target immutable/version/owner/deletion history before SQL but do not police unrelated dirty state; direct ORM/session writes outside `JobPersistenceService` remain unsupported and not universally immutable.
- Plain JSON has no mutation-tracking wrapper; supported transitions replace ordinary untracked in-place JSON with the locked persisted value before lifecycle/version flush.
- Every transition requires the exact observed version. Same-version contenders have one winner; the caller decides whether and when to reload and issue a new command after a stale-version error.
- A locked matching version of `2147483647` raises `JobVersionExhaustedError` before legality, clock, mutation, or flush; no attempt is made to persist `2147483648`.
- A committed pending Job is durable but inert; publication/claim/execution is absent.
- Direct-user/system listing and pagination are absent; creators retain Job identifiers.
- Retry, idempotency, cancellation, timeout, ordering, delivery, leases, and dead-letter behavior are absent.
- PostgreSQL and future Redis publication are not atomic; no outbox is approved.
- Supported executable Job kinds remain undefined until a later producer/worker contract.
