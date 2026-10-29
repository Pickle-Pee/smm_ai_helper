# Telegram hardening baseline — 2026-10-22

Base: `a51a12d44da602d96a22cb99e26026898c8006a2`, fetched `origin/master`.
`master...sale-ready`: 122 / 0 commits. Master is the explicit task base because
it contains current Copilot, positioning, worker cancellation and telemetry work.
The original checkout contains unrelated modifications; implementation uses the
separate `codex/telegram-production-hardening` branch/worktree. No old branches merged.

## Authoritative execution and state

`create_dispatcher` registers menu → Copilot commands → fixed workflow → agents /
images → history → primary chat. Private free text delegates to `copilot_flow`
only in empty/Copilot FSM. CONVERSATION delegates once to the legacy HTTP chat.
Handlers never invoke providers. MarketingCopilotService/graph runtime owns graph
acceptance and persisted results; MarketingWorkflowService owns the fixed MVP.
Standalone tasks use TaskPipelineService. PostgreSQL owns durable state; Redis
wakeups and Telegram MemoryStorage do not replace it.

| Interface | Authoritative backend | Local state / recovery |
| --- | --- | --- |
| `/start` | none | menu only |
| free text, `cp:` URL roles/confirmation | `/copilot/execute` | revision+nonce+64-event ledger; pre-run state expires on restart |
| `/new`, `/cancel` | local pre-run reset | cannot cancel accepted backend work |
| `/copilot_status`, `cs:` | `/copilot/runs/{id}` | reversible 64-hex ID, restart-safe |
| `/copilot_runs`, `cr:` | `/copilot/runs` | backend owner-scoped pagination |
| CONVERSATION, `action:` | `/chat/message` | process-local suggested-action mapping |
| agent menu, clarification | `/tasks/start`, `/tasks/answer` | legacy FSM; persisted completed tasks |
| image menu | `/images` | explicit image FSM; backend owns files |
| `/history`, `task_show:`, detailed result | `/tasks/by_user/{actor}`, `/tasks/{id}` | database results independent of FSM |
| `task_repeat:` | `/agents/{type}/run` | deliberate new synchronous generation |
| `/brand`, `/analyze`, `/context` | `/workflows/profile`, `/workflows`, context patch | fixed workflow persisted |
| `/runs`, `/status`, `/result`, `/redeliver`, `mvp:` | `/workflows` | durable artifacts / continue / delivery retry |
| delivery loop | internal delivery claim / ACK | PostgreSQL lease+claim token; recoverable at-least-once send |

## Existing protections retained

- SimpleEventIsolation serializes each FSM key, not all users globally.
- Pre-run callback revisions/nonces and event ledger reject recent duplicates and
  stale keyboards; durable actor/request-key identity prevents duplicate graph starts.
- Owner-scoped run/task/image routes and bearer+Telegram actor authentication.
- Graph acceptance, jobs, lease fencing, worker recovery, independent delivery.
- Saved reads do not generate; synchronous Copilot results do not promise durable replay.
- Plain text Copilot rendering and UTF-16 splitting, strict HTTP DTO parity tests.
- Fixed opt-in Mentor consumes saved analysis/creative artifacts. No saved graph
  strategy explanation endpoint exists at baseline.

## Confirmed findings

| ID | Classification | Original behavior / reproduction | Cause |
| --- | --- | --- | --- |
| TG-01 | CONFIRMED_DEFECT | repeated legacy button executes again; equal text can reactivate old keyboard | deterministic text hash, no consumption |
| TG-02 | CONFIRMED_DEFECT | malformed task ID raises; repeated task button creates new calls | unchecked split/int; no logical one-shot identity |
| TG-03 | CONFIRMED_RISK | model-provided external image URL receives service/actor headers; response unbounded | unrestricted authenticated GET and response.content |
| TG-04 | CONFIRMED_DEFECT | successful invalid JSON raises JSONDecodeError; list error raises AttributeError; arbitrary error detail displayed | unvalidated backend JSON/raw detail |
| TG-05 | CONFIRMED_DEFECT | late sentinel disappears from detailed results | formatter `[:4000]` before splitting |
| TG-06 | CONFIRMED_DEFECT | timeout starting task silently invokes alternate legacy execution | fallback conflates ambiguous acceptance and unsupported endpoint |
| TG-07 | CONFIRMED_DEFECT | corrupt nested saved strategy raises AttributeError | formatters trust nested shapes |
| TG-08 | CONFIRMED_RISK | same-actor commands wait through up to 300s; delivery / update tasks may outlive bot session | FSM lock across HTTP; incomplete shutdown ownership |
| TG-09 | CONFIRMED_DEFECT | saved graph strategy cannot request case-specific explanation | fixed Mentor only supports creative workflow |

Isolated baseline source reproduction of TG-04 produced JSONDecodeError,
AttributeError and exposed a synthetic SQL/error sentinel. Other findings are
protected by behavioral regressions named in the final report.

## Baseline verification

On an archive of exactly the base SHA, with fake credentials and provider URL
`http://127.0.0.1:9`:

`python -m pytest -q tests/test_telegram_copilot.py tests/test_release_telegram.py tests/test_telegram_copilot_postgresql.py`

**119 passed, 9 skipped, 4 warnings**, 8.20s. Skips require disposable PostgreSQL;
they are not passes. Existing warnings: Pydantic class Config deprecations.
The implementation later enables PostgreSQL and Redis tests on isolated services.

## Coverage plan

| Area | Existing coverage | Missing/new evidence |
| --- | --- | --- |
| URL/FSM/routing | test_telegram_copilot | 10 real-dispatcher callbacks, slow same-actor controls |
| graph acceptance/recovery/security | test_release_telegram, test_release_hardening_postgresql | enabled real DB run |
| legacy actions/repeats | action label tests, HTTP security | one-shot concurrency, stale/restart, malformed IDs |
| media/delivery | MVP/release worker tests | credential destination, byte cap, redirect, lost ACK/cancel |
| saved rendering | Copilot UTF-16 tests | long legacy tails and malformed nested structures |
| Mentor | fixed MVP workflow tests | graph strategy eight sections, saved lineage, concurrent creation, restart, feedback |
| process | release operations/container probes | drain active handlers before closing session |

Docker CLI is installed but its Linux daemon pipe is absent. Container SIGTERM
and recreation checks therefore require CI; native PostgreSQL/Redis are available.
