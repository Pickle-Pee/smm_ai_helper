# Durable Job persistence verification

Status: pre-implementation evidence template. Nothing in this document claims that the Job runtime, migration, or tests exist or pass.

## Identification

- OpenSpec change: `add-durable-job-persistence`
- Planning base: `bcdbd509450dd9d391ef7eeebf34134887264838`
- Planned branch: `agent/add-durable-job-persistence`
- Planned migration parent: `20260814_0003`
- Planned migration revision: re-check the sole head during apply; design proposes `20260825_0004`
- Planning task accounting after final transition reconciliation: 261 total; 16 checked reconciliation tasks; 245 pending runtime/evidence tasks
- Implementation commit: pending
- Implementation PR: pending

## Contract evidence to record after implementation

| Area | Required evidence | Result |
| --- | --- | --- |
| Model/table | Exact fourteen columns, including non-negative service-managed `version`, SQL/Python types, nullability, callable/application defaults, server defaults, and absent fields | Pending |
| Enum | Exact `pending`, `running`, `succeeded`, `failed` membership/order and no synonyms | Pending |
| Ownership | Exact run/direct-user/system truth table; all four `Job.user`/`User.jobs`/`Job.marketing_run`/`MarketingRun.jobs` contracts; no anonymous class; owner authorization remains upstream | Pending |
| Foreign keys/deletion | User and MarketingRun `CASCADE`; loaded/unloaded ORM behavior; no nullification/reclassification; operational non-audit retention | Pending |
| Immutability | Pre-SQL rejection of tracked target immutable/version/owner relationship/owner collection/deletion history; untracked in-place JSON reload; unrelated dirty-state preservation; defensive copy; no shared default; no `MutableDict`; unsupported direct-session behavior | Pending |
| Identifier/kind | Exact UUID-hex, permissive existing run-ID validation, kind/step grammar, no normalization | Pending |
| JSON domain | Exact containers/scalars, signed 64-bit integers, finite floats, Unicode/U+0000, cycles, depth 16, deterministic serialization | Pending |
| JSON limits | Payload 262,144 bytes; result 1,048,576 bytes; exact-boundary and one-byte-over evidence | Pending |
| Error safety | Caller-sanitized exact string, ASCII-whitespace predicate, 4000-character limit, no exception/stringification/traceback/provider copying | Pending |
| Constraints | Each of eleven named predicates independently reflected and acceptance/rejection tested | Pending |
| Indexes | Primary key plus exact run/status composite indexes; no user/kind index | Pending |
| Lifecycle | Every legal edge, skipped/backward edge, same-state request, and terminal successor independently evidenced with exact `0 -> 1 -> 2` version increments | Pending |
| Version | Creation at `0`; mandatory exact built-in expected version; range/boolean/subclass rejection; stale precedence; one increment only on success; no caller write/reset/wrap | Pending |
| Time | One injected UTC clock call; creation/start/completion equalities; UTC/microseconds; reversed-time rejection | Pending |
| Service precedence | Job ID, expected version, target status, outcome input, dirty target, missing row, stale version, locked legality, clock/order, and database failure order; no refresh | Pending |
| Queries | Malformed/missing lookup and unbounded deterministic run listing; explicit absence of user/system listing | Pending |
| Transactions | Dirty gate before SQL; exact row lock/reload; one add/flush; no commit/rollback/refresh/autoflush; caller rollback; atomic workflow relationship | Pending |
| Concurrency | Exact `SELECT ... FOR UPDATE`, post-lock expected-version comparison, one winner per observed version, both adjacent lock orders, valid newly observed sequential transition, repeated-terminal stale behavior | Pending |
| Migration | Sole-parent continuity, isolated upgrade, reflected schema, downgrade, re-upgrade | Pending |
| Compatibility | MarketingRun/Artifact, API/Telegram, pipeline, Orchestrator, Quality Gates, Registry | Pending |
| Isolation | Redis; worker/queue; LLM/OpenAI; QCService; TaskPipelineService; commit/rollback; API/Telegram evidence recorded separately | Pending |
| Packaging | No dependency, Docker, Compose, CI, environment, or lock-file impact | Pending |

## Exact database predicate checklist

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

## Security evidence to record

- System Job creation is reachable only from explicitly reviewed trusted internal code: pending.
- No public/Telegram anonymous or system-owner switch exists: pending.
- Payload/result producers exclude secrets, credentials, raw prompts/provider responses, binary media, and unnecessary PII: pending.
- Persistence performs no automatic secret detection: pending.
- Failed transitions accept only a sanitized string and never an exception object: pending.
- Stable errors contain no raw payload/result/error value: pending.

## Module Registry compatibility snapshot to re-verify

- Version: expected `1.0.0`
- Descriptor count: expected 15
- Execution bindings: expected 0
- Normalized JSON SHA-256: expected `25261485245902066cb6c59ef6cc612b18ab4cdabeebff6768e49816ba716918`
- Actual after implementation: pending

## Commands to execute after implementation

Do not mark any command complete until it actually exits successfully.

- [ ] Focused Job model/default/relationship tests.
- [ ] Focused validators/service/lifecycle/immutability tests.
- [ ] Focused PostgreSQL constraint/transaction/concurrency tests.
- [ ] PostgreSQL migration upgrade from `20260814_0003`.
- [ ] PostgreSQL downgrade one revision.
- [ ] PostgreSQL deterministic re-upgrade.
- [ ] `.venv\Scripts\python.exe -m pytest -q`
- [ ] `.venv\Scripts\python.exe -m compileall app bot`
- [ ] `.venv\Scripts\python.exe -m alembic heads`
- [ ] `openspec validate add-durable-job-persistence --strict`
- [ ] `openspec validate --all --strict`
- [ ] `git diff --check origin/sale-ready...HEAD`
- [ ] `git status --short`
- [ ] Prohibited-path/dependency/Docker/CI audit.

## Compatibility evidence to record after implementation

- MarketingRun behavior: pending.
- MarketingArtifact behavior: pending.
- `TaskPipelineService` behavior/import/call counts: pending.
- TaskRouter, AgentRunner, and AgentRegistry: pending separately.
- Marketing Orchestrator planning-only behavior: pending.
- implemented Quality Gates planning-only behavior: pending.
- Module Registry identity: pending.
- public API/schemas/presenters: pending.
- Telegram handlers: pending.
- Redis calls/configuration: pending.
- worker/queue/polling/scheduler calls: pending.
- LLM/OpenAI calls: pending.
- model-based `QCService` calls: pending.
- persistence commit/rollback/refresh: pending.
- URL/image/provider/external calls: pending.
- dependency manifests, Docker, Compose, CI, and environment: pending.

## Limitations to carry into implementation report

- Jobs are operational aggregate records, not retained audit history; deleting a run/user deletes its owned Jobs.
- Supported transitions reject tracked target immutable/version/owner/deletion history before SQL but do not police unrelated dirty state; direct ORM/session writes outside `JobPersistenceService` remain unsupported and not universally immutable.
- Plain JSON has no mutation-tracking wrapper; supported transitions replace ordinary untracked in-place JSON with the locked persisted value before lifecycle/version flush.
- Every transition requires the exact observed version. Same-version contenders have one winner; the caller decides whether and when to reload and issue a new command after a stale-version error.
- A committed pending Job is durable but inert; publication/claim/execution is absent.
- Direct-user/system listing and pagination are absent; creators retain Job identifiers.
- Retry, idempotency, cancellation, timeout, ordering, delivery, leases, and dead-letter behavior are absent.
- PostgreSQL and future Redis publication are not atomic; no outbox is approved.
- Supported executable Job kinds remain undefined until a later producer/worker contract.
