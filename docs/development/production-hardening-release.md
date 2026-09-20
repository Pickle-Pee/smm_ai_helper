# Task L — production hardening evidence

Base SHA: `1fb46fd3a923620f41e9d5072d394115e9c88e04`, merged PR #65 in `sale-ready`.
Task branch: `codex/production-hardening-release`. Final reviewed head and CI links
are recorded in the PR; no automatic merge or `sale-ready -> master` PR is authorized.

## Implementation and decisions

- Added `GET /copilot/runs` with authenticated owner/type scoping, bounded pagination
  and a four-field public projection from existing MarketingRun rows. No migration.
- Added `/copilot_runs` and stateless paging/selection in Telegram. Recovered results
  always come from accepted backend artifacts. Lost acknowledgement is recoverable.
- Kept pre-run selections ephemeral; added dialog nonces to reject old callbacks
  even when the same Telegram message is redelivered after local state loss.
- Preserved three graph attempts with one model HTTP request each, including retry
  classification for remote protocol failures. Added request/run/job correlation.
- Added safe database/programming failure envelopes, readiness, startup validation
  and content-free operational logging across backend/worker/bot and legacy providers.
- Added event-coordinated crash/snapshot/concurrency tests and a container recovery
  harness using fake Responses/Telegram transports only. Existing required/optional
  topology, fixed workflow and legacy regression suites remain in place.
- Updated Tasks G–K development contracts and ARCHITECTURE to describe the current
  HTTP/Telegram/worker composition rather than older disconnected implementation stages.

## Test evidence and bounded observations

The focused API, Telegram, graph, production worker, Strategy Builder, owned-site,
security, fixed workflow and legacy chat/task selection ran on Windows/Python 3.12
and a disposable PostgreSQL 15 database: **378 passed, 5 skipped**. The skips require
Redis; local Docker was unavailable. A first full run encountered a stopped local
test PostgreSQL and an outdated logger fake; it is not passing evidence. The test
database was restarted and the logger fake updated without changing fallback behavior.

Independent new stress runs observed:

| Exercise | Observed result |
| --- | --- |
| 10 identical execute requests, pool size 5 / overflow 0 | 10 × 202, one run/revision, 3 Jobs and 3 accepted artifacts |
| 10 requests split between two plans under one key | 5 × 202 and 5 × 409, exactly one authoritative plan |
| 20 concurrent list/status reads, same pool | All 200, SQL SELECT/SET only, no provider/wakeup/write |
| 20 readers with a progressing worker | All coherent 200 snapshots; worker completes |
| Two worker lanes / four initial research nodes | Two simultaneous leases/providers, duplicate claims rejected; barrier and seven final artifacts preserved |
| Crash during provider / after provider before persistence | Replacement after expiry succeeds, one accepted artifact per node |
| Old worker completes after replacement | finish returns false; replacement remains authoritative |

Initial local stress elapsed times were approximately 2.12s (identical execute),
1.80s (conflict) and 1.78s (polling exercise including worker progress). These are
fake-provider correctness observations on this machine, **not production throughput**.
The tests impose bounded completion deadlines, not invented latency SLAs.

The full suite, exact current-head CI/container counts and final matrix are updated
after verification. Container recovery is a release gate until it has actually passed.

## Coverage map

| Area | Evidence |
| --- | --- |
| API/recovery/ownership | `test_release_hardening_postgresql.py`, `test_copilot_api*.py`: list bounds, unknown/foreign equivalence, fixed-run isolation, safe DB failure |
| Telegram restart/replay | `test_release_telegram.py`, `test_telegram_copilot*.py`: real HTTP adapter, lost ack/timeout, event-ledger loss, nonce isolation, recovered presentation |
| Durability/fencing | `test_graph_postgresql.py`, release crash tests, `test_production_worker_postgresql.py`: atomic artifacts/Jobs, SQL failure, expired claims |
| Redis | release API wake-failure tests plus existing real Redis production-lane tests; container probe stops Redis before start and through active execution |
| Retry budget | 408/429/500/502/503/504/timeout/connection/protocol => 3; 400/401/403/invalid JSON/structured output => 1; existing explicit contract failures terminal |
| Polling | event holds reader snapshot while worker completes; load test checks SELECT/SET-only SQL and zero provider calls/wakeups |
| Strategy topology | `test_strategy_builder_postgresql.py`: minimum, maximum, optional market/competitor/experiments failures, required POSITIONING/CMO failure; release maximum graph uses two lanes |
| Owned source | `test_product_context*.py`, `test_copilot_api_postgresql.py`, Telegram owned-confirmation E2E: changed snapshot, unsafe/unavailable/extractor failure, clarification, graph and final strategy |
| Legacy | full pytest: chat, tasks/agents, fixed workflow/delivery, images, BrandProfile, Telegram `/analyze`, task/history and actions |
| Architecture | transitive import guard in `test_telegram_copilot.py` and real Telegram -> HTTP -> production composition -> SQL -> worker -> accepted presentation E2E |
| Operations | `test_release_operations.py`, startup/worker tests and `scripts/check_copilot_release.py`: safe logs/readiness/configuration and OS SIGTERM |

## MVP limits and release matrix

The durable guarantee is **at-least-recoverable** presentation, not exactly-once
Telegram delivery. External model execution is at-least-once after worker crashes.
Pre-run state is lost on bot restart; old callbacks fail closed. DIRECT/SINGLE remain
synchronous and uncached, and retry may repeat work. Offset pages may shift as new
runs arrive. Shared service authentication is not public user authentication. No
autonomous search, replanning, new modules or graph image generation was added.

| Area | Status before final CI |
| --- | --- |
| API | PASS — focused API/recovery and bounded concurrency |
| Telegram | PASS — restart/replay/presentation through real HTTP adapter |
| PostgreSQL durability | PASS — real DB crash/atomicity/fencing tests |
| Redis loss | PASS — wake failures with DB scans; real container gate pending |
| Worker restart | PASS — cancellation/expiry/replacement; OS gate pending |
| Provider transient retry | PASS — single-attempt transport × three durable attempts |
| Fencing | PASS — stale completion rejected, no duplicate accepted artifact |
| Ownership | PASS — authenticated owner/type-scoped lists and reads |
| Idempotency | PASS — ten concurrent callers, conflict has one winner |
| Presentation | PASS — accepted artifacts, strategy/experiments, visible limits |
| Legacy regression | Known verification limitation — full suite in progress |
| Container recovery | Known verification limitation — CI not yet verified |
| Migration | PASS — no new migration; head `20260917_0009`, alembic check clean |
| Observability | PASS — correlation identifiers, safe errors, no raw provider body logs |

Do not call the release ready until the remaining verification gates and any P1/P2
review findings are closed. Deployment/startup, manual smoke, retained components
and image/code rollback without deleting runs are in the
[production checklist](../operations/copilot-production-checklist.md).
