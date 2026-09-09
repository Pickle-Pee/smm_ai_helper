# MVP verification — 9 September 2026

The fixed Telegram MVP is implemented and verified locally and in GitHub CI. This report describes the checked code, not a production deployment or a live model-quality acceptance. Runtime/configuration candidate: `38200f40a6857baed7cb1e843ddc8bb14b7c180e`; container verification was added in `2806675`, task branch `codex/telegram-marketing-mvp`, [PR #53](https://github.com/Pickle-Pee/smm_ai_helper/pull/53). Obtain the final integration tip with `git rev-parse sale-ready`; the final task response records the merge SHA.

## Consolidation and commits

Remote refs were fetched again before final integration. `origin/sale-ready` remained `bcdbd509450dd9d391ef7eeebf34134887264838`. Durable Job `72ac01c29a1221d529a89921faacdfd62914b0ba` was four commits ahead and was fast-forwarded into a dedicated consolidation branch. Expert Core, Module Registry, deterministic Orchestrator and Quality Gates were retained.

The old `agent/add-marketing-workflow-persistence` branch has the same workflow persistence service and migration as the integrated code. Its older aggregate models must not replace current Job models. `agent/add-module-registry-foundation` has byte-identical `app/module_registry` files. Older BrandProfile branches are covered by the current API/service and subsequent identity/security fixes; `feat/chat-brand-context` has the same ChatService, and `fix/telegram-brand-profile-id` has the same BrandProfileService. Equivalent or superseded patches were not blindly re-merged. Master remains release history and was not modified. The source review mentioned draft PR #42; its current status could not be confirmed through `gh` (HTTP 401).

| Commit | Result |
| --- | --- |
| `1af194c` | Correct disposable PostgreSQL fixtures and enable Durable Job DB evidence in CI |
| `01f569d` | Adopt implementation → tests → review; retain existing OpenSpec contracts as reference |
| `db8a452` | Public-network URL fetch boundary and independent cache transactions |
| `efb2a34` | Bot credentials/ownership, callback actor, replayable atomic task completion and history |
| `10e0012` | Durable fixed workflow, leases/retries, artifact/Job/run/delivery transaction, schema reconciliation |
| `5a078b0` | Telegram commands, saved continuations, mentor opt-in and provider-protocol tests |
| `38200f4` | Compose services, persistent media, offline smoke and launch documentation |
| `13409f4` | Local verification report |
| `2806675` | Real image build, Compose startup and container/media recovery verification in CI |

Work used `codex/consolidate-durable-jobs`, `codex/harden-existing-flows` and `codex/telegram-marketing-mvp`, with local fast-forward integration into `sale-ready`. The existing IDE stash was preserved: `On agent/add-durable-job-persistence: local IDE metadata before durable job reconciliation`. No resets, forced pushes, branch deletions or credential changes were performed.

GitHub access subsequently recovered. The task branch was published normally to the existing remote and PR #53 was created against `sale-ready`; no alternative account or credentials were used. CI on `13409f4` passed all 679 tests, including real Redis. [CI on `2806675`](https://github.com/Pickle-Pee/smm_ai_helper/actions/runs/34327858045) additionally built and exercised the Docker image and verified container recreation. The target branch is unprotected; integration uses a normal reviewed PR merge, with no force push or protection bypass.

## Working behavior and changed files

- **Analysis:** `/brand` stores explicit business context; `/analyze` snapshots it with run-specific overrides, asks for missing fields, queues analysis of a public competitor URL and delivers a saved structured result. Positioning, strengths/weaknesses, customer hypotheses, differentiation and practical brief remain tied to captured evidence.
- **Creative:** the saved analysis drives a hypothesis, trigger, offer, headline, CTA, locally rendered banner and contiguous 15–60-second scene script. Input snapshots and lineage are retained. Images are owned and stored on a shared backend/worker volume.
- **Mentor:** the separate explanation button uses that same analysis and creative. It explains principle, evidence, alternative, limitations/failure conditions and validation plan. It never runs automatically.
- **Recovery:** deterministic actor/request and run/step keys, PostgreSQL claims with fencing, three bounded execution attempts, and independent ordered delivery parts survive process restarts and Redis loss. `/runs`, `/status`, `/result`, `/redeliver` work from durable state.
- **Confirmed defects:** callback uses the pressing actor; IDs alone no longer authorize API access; URL/DNS/IPv4/IPv6/redirect checks block private targets; cache operations do not use/commit the caller's AsyncSession; standalone completion and history persist atomically; nonempty history serializes datetime successfully; long output is delivered in full.

Primary runtime changes are in `app/security.py`, `app/services/safe_http.py`, `url_analyzer.py`, `task_completion_service.py`, `task_pipeline.py`, `task_session_service.py`, `image_orchestrator.py`, `app/images/template_renderer.py`, `app/workflows/`, `app/worker.py`, `app/routers/workflows.py`, protected existing routers, `app/models.py`, `app/schemas.py`, and `bot/backend.py`, `bot/delivery.py`, `bot/rendering.py`, workflow/chat/history/task handlers and `bot/main.py`. Launch changes are in Dockerfile, Compose, `.dockerignore`, `.env.example`, CI and `scripts/smoke_mvp.py`. Tests accompany the behavior in the corresponding `tests/test_*` files.

Registry remains version 1.0.0 with 15 descriptors and zero execution bindings. Its deterministic planning APIs remain planning-only. The fixed executors compose the canonical Expert Core and use an explicit Quality Gates metadata adapter; gates do not establish semantic truth.

## Actual checks

Interpreter: project `.venv/Scripts/python.exe`, Python 3.12.14. Database: real disposable PostgreSQL 15.19, bound to loopback `127.0.0.1:55439`. Targets were separate `durable_job_test_local` and `smm_mvp_test_local` databases; shared/user data was not migrated or downgraded.

| Executed check | Actual result |
| --- | --- |
| Initial candidate baseline | 596 passed, 13 skipped (PostgreSQL suite initially disabled) |
| Full suite after URL/access/task fixes, both disposable DB variables set | 648 passed, 0 skipped |
| Final `python -m pytest -q --tb=short`, both DB variables set | **678 passed, 1 skipped, 126 warnings**, 22.49 s |
| `python scripts/smoke_mvp.py`, disposable MVP URL set | **14 passed**, 15.94 s; all external providers/Telegram are doubles |
| `python -m compileall -q app bot scripts` | Passed |
| `git diff --check` and staged equivalent | Passed; Windows LF/CRLF notices are not whitespace errors |
| `python -m alembic upgrade head` | Passed on disposable PostgreSQL |
| `python -m alembic check` | Passed: no new upgrade operations detected |
| `python -m alembic heads` | Single head `20260909_0007` |
| Migration round trips and data preservation | Passed in real PostgreSQL tests: Durable Job parent → revision → parent → revision; MVP 0005 → head and 0006 → head; legacy rows/backfilled dates retained |
| Native Uvicorn subprocess, real local HTTP | Startup, `/health` and authenticated PostgreSQL-backed `/workflows` passed; subprocess stopped afterwards |
| `docker --config .local-test/docker-cli compose --env-file .env.example config --quiet` | Passed |
| GitHub Ubuntu / Python 3.11 full suite, PostgreSQL 15 and Redis 7 | **679 passed, 0 skipped, 19 warnings**, 19.71 s, run `34327858045` |
| CI `docker compose up --build --wait ... db redis backend worker` | Passed: actual image build, migrations, health and worker startup; polling bot excluded |
| Tests inside the built image with real PostgreSQL and Redis | **16 passed, 0 skipped, 5 warnings**, 15.35 s |
| `check_container_persistence.py seed`, force-recreate backend/worker, `verify` | Passed: changed container IDs, persisted run, identical shared-volume image bytes, foreign-owner 404 |

Regression evidence includes competing starts/claims/completions, process death immediately after claim commit and execution by a replacement process, Redis publication crash recovery, stale attempt rejection, bounded failures/timeouts, delivery outage/backoff/restart, atomic result commit rollback, foreign run/job/artifact/profile/task/image denial, callback actor, missing context, malformed output/evidence/lineage, confidence inheritance, full long-text delivery and banner text fitting in Cyrillic. The protocol smoke uses production UrlAnalyzer, Responses adapter, image-brief adapter, ImageOrchestrator and renderer with a closed fake HTTP transport; no real network provider can be reached in that test.

The **one local skip** is `test_real_redis_wakeups_duplicates_and_reconnect`: no local Redis server/`REDIS_TEST_URL` was available. It passed in both GitHub CI environments with Redis 7; there are no remaining skipped tests in CI. Redis outage handling and DB recovery are also covered locally. Remaining warnings concern pre-existing Pydantic class Config, naive `datetime.utcnow()` and Alembic path separator deprecations; GitHub also annotates the existing action runtime deprecation.

Docker Engine could not start on this workstation; Docker reported an unavailable daemon and a stale Docker Inference socket. Docker build/startup, Linux rendering and container recreation with real named volumes were therefore executed in the disposable GitHub CI project. Its provider endpoint is disabled and all text/image/Telegram integrations are doubled; the project and its test volumes are removed after the job. Local PostgreSQL checks used official portable PostgreSQL binaries. No OpenSpec artifacts were edited for the new workflow, so a separate OpenSpec validation/approval cycle was not run; the user explicitly replaced that process.

## Migrations and operation

Added after the integrated Durable Job migration: `20260908_0005` (completion response), `20260908_0006` (execution/delivery), `20260909_0007` (legacy nullability reconciliation). No already merged migration was rewritten. Migration 0007 uses a companion date or migration time for unknown historical dates and `unknown` for missing task status; these fallbacks are not historical facts.

Set `DATABASE_URL`, `REDIS_URL`, `OPENAI_API_KEY`, `TELEGRAM_BOT_TOKEN`, `BOT_BACKEND_TOKEN`, `API_BASE_URL`, `IMAGE_STORAGE_PATH` as described in README. `WORKER_CONCURRENCY=2` and `WORKFLOW_TIMEOUT_SECONDS=240` are defaults. With a working Docker Engine: `docker compose up --build -d`. Without Docker: apply `python -m alembic upgrade head`, then run `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`, `python -m app.worker`, and `python -m bot.main` in separate processes with the same environment.

## Remaining acceptance and limits

Real paid model/image calls, messages to real Telegram users, and model-content quality/latency/cost remain live acceptance checks. Infrastructure and recovery checks passed in CI. No production deployment was performed. Use a dedicated Telegram test bot/private chat and a small known public competitor page for later authorized live acceptance: save a profile, run analysis, generate creative, restart worker/backend, request mentor, retrieve `/result`, and verify delivery and readable banner text.

Only public HTML content from one page is analyzed. Authentication walls, browser-only sites, unsupported compressed responses and non-HTML documents can fail with insufficient source information. Recommendations are hypotheses and require real validation. There is no general 15-module execution framework, final video editing, campaign/CRM integration, production hardening or external exactly-once guarantee. An ambiguous model crash can repeat a charged call; an accepted Telegram send with lost acknowledgement can duplicate a message. Durable completion and retries never discard a committed artifact or regenerate solely because delivery failed.
