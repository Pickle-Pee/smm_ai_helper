# Production graph worker lane

`python -m app.worker` now runs fixed Marketing MVP and generic durable graphs
in the same process. It does not start API serving, Telegram polling, Copilot
intent interpretation or owned-product acquisition. The dedicated
[Copilot API](production-copilot-api.md) and internal authorized callers persist compiled plans;
the worker restores their ContextPackets and predecessor results from PostgreSQL.

```text
PostgreSQL Job / JobExecution (authoritative)
   ├ marketing.step        → MarketingWorker → MarketingExecutors
   └ orchestration.module  → ModuleGraphWorker → ModuleExecutorDispatcher

Redis (expendable wakeup hints)
   ├ smm:marketing:wakeups:v1      → fixed lanes
   └ smm:orchestration:wakeups:v1  → graph lanes

build_production_graph_runtime
   ModuleRegistry.load("1.2.0")
     → six coherent exact ModuleExecutorRegistry bindings
       → GraphExecutionService → ModuleGraphWorker
```

## Composition and model boundary

`app/orchestration_runtime/composition.py` explicitly binds COMPETITOR_ANALYSIS,
POSITIONING, CREATOR, MARKET_ANALYSIS, VIRTUAL_CMO and EXPERIMENTS. Registry 1.0
remains metadata-only; defaults in internal factories are unchanged. Existing
persisted 1.1 plans retain their version and can execute with the same exact
bindings in the 1.2 inventory. No plan is upgraded during reload.

`production_model_call` adapts the existing `app.llm.openai_text.chat` Responses
transport with `single_attempt=True`. It sends the executor's instruction, input
and JSON Schema with `strict=True`, the configured `DEFAULT_TEXT_MODEL_HARD`, and
a hard maximum of 4000 output tokens. It performs one HTTP request: no internal
retry, schema fallback, budget expansion or output repair. Incomplete responses
are terminal; empty/malformed text goes to the unchanged strict executor parser.
The adapter returns text only; raw provider envelopes are never persisted or
logged by this path. Instructions request concise findings/rationales, never
hidden chain-of-thought. Provider-specific dependencies stay outside executors.

Legacy `chat` callers keep their existing retry/fallback behavior. The new opt-in
transport policy is necessary because its legacy fallback can remove the schema
and expand the token budget. Production graph tests exercise the actual HTTP
transport with `httpx.MockTransport`, as well as an injected model capability.

COMPETITOR_ANALYSIS and MARKET_ANALYSIS share the existing cache-free
`build_public_site_analyzer()` capability over `UrlAnalyzer.analyze_url`, safe
public DNS/socket/redirect validation and bounded fetching. No new HTTP stack,
search, owned-site acquisition or database transaction around providers is added.
`OwnedProductEvidenceService` remains a caller-owned pre-Copilot operation.

## Attempts, timeouts and fencing

JobExecution alone owns graph retries: at most **three attempts per Job**, with
the existing 5s/10s backoff. Each attempt can call the text provider at most once,
so the maximum is **three model HTTP requests per graph Job**, independent of
`HTTP_RETRIES`. A failed URL fetch can use an attempt before calling the model.
The safe analyzer retains bounded redirect handling, with no new fetch retries.

TimeoutError, httpx transport failures (including remote protocol errors) and HTTP 408/429/500/502/503/504 are
transient. The classifier walks explicit `__cause__` chains with cycle protection
for existing wrapped provider errors. An arbitrary RuntimeError, malformed
structured output, contract violation, other HTTP status or application bug is
terminal. Errors are persisted as existing safe codes, never raw provider data.

Startup requires `0 < HTTP_TIMEOUT < GRAPH_TIMEOUT_SECONDS < GRAPH_LEASE_SECONDS`.
Defaults are 60 / 300 / 330 seconds; the outer graph timeout bounds the complete
dispatch (including source acquisition). Graph timeout is bounded to 5–900s,
lease to 6–960s. Completion/failure remains fenced by claim token and lease.
Stale workers cannot persist results after replacement. External effects still
do not have an exactly-once guarantee.

## Concurrency and recovery

`WORKER_CONCURRENCY` retains its existing meaning: **fixed lanes only**, default 2,
range 1–8. `GRAPH_WORKER_CONCURRENCY` independently selects graph lanes, default 1,
range 1–8. The default process therefore has **three lanes total (2 + 1)**; rollout
adds capacity for one graph execution without reducing fixed capacity. All lanes
run as independent tasks. An iteration failure logs only lane/error type and
waits 2s before trying again; it does not cancel sibling lanes.

Each loop scans PostgreSQL first, then waits at most about a second for a Redis
hint when idle. Redis clients bound connect/socket timeouts; failed waits sleep
1s before the next DB scan. Lost, stale, unknown or cross-kind hints do not create
or authorize work. Both SQL claim queries filter their canonical Job.kind. The
fixed list key is unchanged and the graph consumer never pops that list.

On SIGTERM (Linux containers) or task cancellation, TaskGroup cancels both lane
families. CancelledError never becomes a Job failure. Per-call HTTP clients close
through their async contexts; the process closes both Redis pools even if startup
or another close fails. Active claims remain recoverable after lease expiry.
There is no background continuation of an interrupted provider call.

## Startup and operation

Before loops start, construction checks explicit Registry 1.2.0, exactly six
bindings, executor coherence, distinct canonical queue keys, the timeout window,
and required callable model/URL capabilities. Normal configuration still requires
a non-empty OPENAI_API_KEY; production composition also rejects whitespace-only
credentials, an empty model name and a non-HTTP/relative provider base URL.
Credential validity at the remote provider cannot be checked without I/O and is
not probed at startup. The offline CI base URL is valid configuration.

Construction makes no network calls. The startup log reports lane counts and
Registry version. No database migration or public/Telegram DTO change is needed.

## Verification

New suites: `test_production_graph_worker.py`, `test_graph_model_adapter.py`,
`test_production_worker_postgresql.py`. Tests cover exact production composition,
startup failure, strict transport, cause chains, loop isolation, queue cleanup,
simultaneous fixed/Strategy Builder execution, DB claim isolation, lost/unavailable
Redis, wrong hints, cancellation and replacement of active leases.

Integration suites require explicitly disposable `MVP_TEST_DATABASE_URL` and
`REDIS_TEST_URL`. No live model or Telegram calls are made. Container CI runs
the new suites alongside the existing fixed provider/DB/Redis suites, starts the
real worker entrypoint with providers disabled, retains the existing persistence
probe, and runs `scripts/check_worker_lanes.py` to verify both families remain up
through Redis outage/recovery and handle SIGTERM with exit code zero.

Manual deployment check: apply existing migrations, start the worker with valid
configuration, observe `Worker lanes ready fixed=2 graph=1 registry=1.2.0` (or the
configured counts), and inspect Job/JobExecution recovery after a worker restart.
The authenticated Copilot API starts approved graphs and Telegram uses that API.
Release checks include active/idle worker SIGTERM, an interrupted provider call,
replacement after lease expiry and accepted artifact recovery after recreation.
See [production checklist](../operations/copilot-production-checklist.md).
