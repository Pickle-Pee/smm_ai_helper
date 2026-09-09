# MVP contracts and standalone replay verification — 2026-09-09

Task branch: `codex/reconcile-mvp-contracts-and-replay`, from `sale-ready` / PR #53 merge `0f6e5145a8c6285862b18eb303f27f51a496926e`. Runtime fix: `1e2d1f8` (`fix(tasks): claim standalone execution before provider calls`). Documentation and this evidence are separate from that runtime commit. The final task response/PR records the integrated tip; this file does not claim production deployment.

## Design and review outcome

Two nullable fields on TaskSessionRecord hold a random claim token and PostgreSQL lease expiry. A short row-locked claim precedes routing and all provider work, including continuation from start. Only the winner applies its answer; contenders refresh persisted state and wait without a DB transaction/connection held. Each external stage is fenced before entry. Completion atomically writes one canonical response, one Task history row and claim release. A later answer replays the saved response without routing/AgentRunner/QC/image calls.

One caller owns one attempt. Default execution timeout is 240 seconds, lease 270 seconds, maximum waiting time 275 seconds and cleanup budget five seconds. There is no lease renewal or automatic standalone worker/retry framework. Provider failure/cancellation/timeout releases only the owner's token; a dead process leaves an expiring durable claim, allowing a subsequent request to recover. Old owners cannot write a result or release a successor. See [full task contract](../task_pipeline.md) for transaction ownership, waiting and external ambiguity.

Migration `20260909_0008` follows `20260909_0007`, adding just token/lease fields and two consistency constraints. Upgrade and downgrade retain answers, completed responses and history. Downgrade loses active ownership metadata. Stop/drain backend requests before rollout/rollback; old code cannot honor these claims. No merged migration was edited.

Self-review covered concurrent final answers, stale ORM snapshots, transaction closure before every external stage, ownership checks, cancellation/timeout/provider/commit failure, process death, successor fencing, atomic history, canonical replay and HTTP compatibility. No changes were made to public schema fields, owner/authentication logic, bot runtime, fixed workflow runtime, Module Registry, generic Orchestrator or canonical prompts. `git diff --quiet sale-ready -- app/module_registry app/marketing_orchestrator app/workflows app/prompts app/schemas.py openspec` returned exit 0.

## Documentation reconciliation

Architecture, product concept/scope, roadmap, current workflow/task contracts and active AGENTS guidance now describe the fixed competitor analysis -> commercial package/banner/scene script -> explicit opt-in mentor implementation. PostgreSQL owns Job/JobExecution/artifacts/delivery, Redis carries wakeups, PostgreSQL due scans recover work, and independent delivery retries never require generation. Quality Gates integration is the explicit workflow adapter before artifact persistence, preserving evidence and lineage.

Registry 1.0.0 remains metadata-only with zero execution bindings. The generic planner and Registry-derived readiness remain PLANNING_ONLY; the fixed executors do not enable arbitrary execution of 15 modules, generic orchestration, autonomous replanning or generic synthesis. Campaign/CRM/final video/production/exactly-once external effects remain outside implemented scope. The roadmap distinguishes each fixed implementation from its broader umbrella intent.

The current prompt source map, Expert Core contract and prompt guidance now identify `app/prompts/expert_core/v1.0.0.md` as runtime, with production Markdown/DOCX retained as provenance. Migration guidance no longer recommends stamping an arbitrary existing database as head. The old contextual-chat migration plan is explicitly labeled historical. Historical foundation verification reports and OpenSpec artifacts retain their branch/base-specific evidence; their older future statements were reviewed as historical, not mechanically replaced.

## Executed verification

Windows: repository `.venv/Scripts/python.exe` (Python 3.12.14), portable PostgreSQL 15.19 on loopback port 55439. Only the explicitly disposable `smm_mvp_test_local` and `durable_job_test_local` databases were used. No user/shared database was downgraded. Test providers/Telegram were doubles.

| Check | Passed | Failed | Skipped | Result |
| --- | ---: | ---: | ---: | --- |
| Final full suite | 694 | 0 | 1 | 206 warnings, 24.69 s; real Redis test skipped because REDIS_TEST_URL was unset |
| Final focused replay/HTTP/Expert Core/migrations suite | 37 | 0 | 0 | 102 warnings, 7.87 s |
| Offline-provider MVP smoke | 14 | 0 | 0 | 80 warnings, 13.40 s |
| compileall app bot | — | — | — | exit 0 |
| git diff --check; cached diff check | — | — | — | exit 0 |
| alembic upgrade head | — | — | — | exit 0, 20260909_0008 |
| alembic check | — | — | — | exit 0, no new upgrade operations detected |

Initial expanded selection: 27 passed / 1 failed / 0 skipped. PostgreSQL fixture setup called Alembic logging configuration, disabling existing application loggers and making the existing diagnostic log test fail when run afterward. The fixture now suppresses only migration logging reconfiguration, preserving pytest capture and application loggers; production logging is unchanged. The subsequent selection passed 33/0/0; additional bounded-wait/constraint cases brought it to 37/0/0. An earlier full selection before those additional cases passed 690/0/1. These intermediate results are not substituted for the final run above.

Warnings are existing Python datetime.utcnow, Pydantic Config and Alembic/FastAPI deprecations; they are not test failures. CI supplies real Redis and Linux/container verification separately; its live result is recorded in the PR checks and final task response, not inferred from local passes.

## Commands actually executed

The verification commands below were executed from the repository root, using `.venv/Scripts/python.exe` for `python`. Repeated checks followed added regression coverage; migration commands ran serially after the full suite, never concurrently with destructive fixtures.

```powershell
$env:DATABASE_URL='postgresql+asyncpg://postgres@127.0.0.1:55439/smm_mvp_test_local'
$env:MVP_TEST_DATABASE_URL=$env:DATABASE_URL
$env:DURABLE_JOB_TEST_DATABASE_URL='postgresql+asyncpg://postgres@127.0.0.1:55439/durable_job_test_local'
$env:TELEGRAM_BOT_TOKEN='test-token'
$env:OPENAI_API_KEY='test-key'
python -m pytest -q --tb=short -ra
python -m pytest tests/test_task_finalization_postgresql.py tests/test_task_completion_postgresql.py tests/test_task_pipeline_service.py tests/test_expert_core_integration.py tests/test_task_replay_http.py tests/test_mvp_migrations.py -q --tb=short
python -m compileall app bot
python -m alembic upgrade head
python -m alembic check
python scripts/smoke_mvp.py
git -c core.safecrlf=false diff --check
git diff --cached --check
git diff --quiet sale-ready -- app/module_registry app/marketing_orchestrator app/workflows app/prompts app/schemas.py openspec
```

Also executed: `git fetch origin`, branch/status/log/diff/stash inspection, task branch creation, explicit staging and conventional commit, and `rg` scans across current docs and historical reports. Read-only CLI invocation errors (incorrect glob/filename/gh JSON-field arguments) were corrected; sandboxed gh authentication failed but the same authorized GitHub query succeeded outside the restricted sandbox without changing credentials. These were not failing runtime checks.

Local logs (ignored, not repository artifacts): `.local-test/replay-focused.log`, `replay-full.log`, `replay-compile.log`, `replay-migrations.log`, `replay-smoke.log`, `replay-contract-scan.log`.

## Focused evidence added

- Real concurrent TaskPipelineService.answer calls, two service instances and independent PostgreSQL sessions; asyncio Events force a contender to observe an active claim before the winner finishes. One router/agent/QC/image path; equal canonical responses, unchanged winning answers, one history row and zero additional calls on replay.
- Every fake provider asserts no open transaction and obtains the task row through another connection with FOR UPDATE NOWAIT, proving the winning caller does not hold its row lock across external work.
- Provider exception, cancellation, timeout and failed completion commit each recover through a later real answer call with no false completed state.
- A separate Python process commits a claim and exits abruptly; it remains authoritative until its persisted expiry is advanced in the test, after which real answer completes. This proves process-independent persistence, not just an in-process lock.
- Expired owner cannot enter another external stage, complete or clear a successor; PostgreSQL rejects invalid claim pairs and completed-plus-active-claim states.
- Clarification releases ownership and later completion retains the existing need_info/done contract; HTTP errors preserve shape and expose Retry-After on 503.
- Bounded busy wait executes no provider; migration downgrade/re-upgrade preserves legacy completed sessions and schema matches model metadata.

## Limitations and remaining live checks

Ordinary concurrent callers share one valid local finalization attempt and one canonical persisted completion. Exactly-once provider effects across ambiguous crashes/timeouts/partitions are not guaranteed: a remote call accepted before cancellation may continue or be repeated after lease recovery, and an unused generated image can remain. There is no exactly-once Telegram delivery promise. Standalone tasks still use synchronous request/replay; background independent delivery belongs to fixed marketing workflows.

Real paid OpenAI/image calls, real Telegram messages and commercial content quality/latency/cost were not tested. Production was not deployed. OpenSpec validation was not run because no OpenSpec files changed. Local real Redis and local Docker/container recreation were not run in this task; use the PR's independent CI results for those environments.

For manual acceptance, use a dedicated test bot and private chat: save a business profile, analyze a small known public HTML competitor page, request creative and then explicitly mentor, verify /result after worker/backend restart. For standalone, use one owned session ID with two concurrent final HTTP answers and a later replay; verify identical responses and one history row. Real calls incur provider costs and require separate live authorization.

Launch after configuring `.env` per README (these launch commands are instructions, not a production run performed by this task):

```bash
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# Separate terminals for the marketing MVP:
python -m app.worker
python -m bot.main
```

## Exact changed files

- `.env.example`
- `AGENTS.md`
- `ARCHITECTURE.md`
- `README.md`
- `app/AGENTS.md`
- `app/config.py`
- `app/main.py`
- `app/models.py`
- `app/services/task_completion_service.py`
- `app/services/task_finalization_service.py`
- `app/services/task_pipeline.py`
- `app/services/task_session_service.py`
- `bot/AGENTS.md`
- `docs/MIGRATION_PLAN.md`
- `docs/development/marketing-mvp.md`
- `docs/development/prompt-governance.md`
- `docs/development/replay-contracts-verification-2026-09-09.md`
- `docs/migrations.md`
- `docs/product/ai-marketing-system.md`
- `docs/product/development-roadmap.md`
- `docs/product/durable-job-persistence.md`
- `docs/product/expert-core.md`
- `docs/product/marketing-orchestrator.md`
- `docs/product/module-registry.md`
- `docs/product/mvp-functional-scope.md`
- `docs/product/orchestrator-quality-gates.md`
- `docs/product/prompt-source-map.md`
- `docs/task_pipeline.md`
- `migrations/versions/20260909_0008_standalone_finalization_claim.py`
- `tests/postgresql_support.py`
- `tests/test_expert_core_integration.py`
- `tests/test_mvp_migrations.py`
- `tests/test_task_completion_postgresql.py`
- `tests/test_task_finalization_postgresql.py`
- `tests/test_task_pipeline_service.py`
- `tests/test_task_replay_http.py`
