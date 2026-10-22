# Telegram hardening implementation report — 2026-10-22

Base: `a51a12d44da602d96a22cb99e26026898c8006a2` (`origin/master`).
Branch: `codex/telegram-production-hardening`. One Draft PR; no merge/deployment.
Draft PR: [#129](https://github.com/Pickle-Pee/smm_ai_helper/pull/129), base `master`.
See the baseline and `../operations/telegram-production-runbook.md`.

## Behavior and compatibility

Telegram continues to delegate to authenticated backend HTTP. Existing execute,
chat, tasks, images, profile and fixed-workflow DTOs are retained. No migrations,
new provider wrappers, queues, jobs or workflow execution engines were added.

Legacy suggested actions and task-repeat buttons are explicitly ephemeral one-shot
actions: consumption happens before HTTP awaits; a fresh history/response is required
for another intentional execution. Saved result buttons remain restart-safe.
An ambiguous standalone start no longer invokes a second execution endpoint.

Image downloads only send credentials to same-origin backend `/images/*.png`, with
redirects disabled, 10 MiB streaming cap and 30-second deadline. All returned images
are attempted; delivery failure does not request new generation. Rendering preserves
complete legacy detail and splits at UTF-16 bounds. Invalid saved shapes produce a
controlled message, and unsuccessful tasks cannot be rendered as successful.

The update middleware keeps same-actor `/new` and `/cancel` responsive during
serialized execution, without mutating the in-flight FSM. It reports the real
cancellation limitation. The bot tracks and drains handler tasks, and delivery
stops before closing the Telegram session. Other users remain independent.

## Findings and regression evidence

All rows below were CONFIRMED_DEFECT/CONFIRMED_RISK in the baseline. Tests are
behavioral reproductions; no assertions were weakened to accept provider errors.

| Finding / priority | Root cause → implementation | Regression evidence | Residual limit |
| --- | --- | --- | --- |
| TG-01 / P1 | reusable text hash → fresh consumed action identity | action consumed under 10 concurrent calls; identical later text cannot reactivate old keyboard; foreign/group/restart rejection | local actions expire |
| TG-02 / P1 | unchecked ID and repeat → strict payloads, actor-bound consumed repeat tokens, owner fetch | malformed callbacks, repeat concurrency/modified agent/restart; saved failure status | synchronous generation has no durable acceptance replay |
| TG-03 / P0 | arbitrary authenticated unbounded GET → shared bounded backend image fetch | malicious origins, URL credentials, redirects, declared/streamed size, all-image delivery failure | 10 MiB cap is intentional; missing persisted file cannot be reconstructed by delivery |
| TG-04 / P1 | raw detail/unchecked JSON → safe status mapping/shape boundary | invalid JSON/list/detail synthetic secret; user messages contain no raw body | legacy handlers retain endpoint-specific safe fallback text |
| TG-05 / P1 | pre-split truncation → full text and UTF-16 send_text | long strategy/analytics/promo/trends tail sent; emoji bounds | Telegram limits visible presentation |
| TG-06 / P0 | timeout fallback reruns work → no fallback after ambiguous start | standalone ambiguous start never calls agents/run | deliberate new start can still incur provider work |
| TG-07 / P1 | nested shape trust → safe saved renderer/history validation | malformed nested strategy and task row handled | malformed stored data needs investigation |
| TG-08 / P0 | lock blocks controls; unowned tasks → immediate truthful control response, owned handler/session lifecycle | real dispatcher slow request + second user; cancellation cleanup and shutdown order | active backend cancellation/new same-user execution unsupported |
| TG-09 / P0 | fixed Mentor lacks graph case link → saved case explanation API/UI | real Telegram→HTTP→PostgreSQL strategy, questions, feedback, restart and foreign actor denial | no new counterfactual strategy synthesis |

Changed files: backend/API additions under `app/marketing_copilot/mentor*` and
`app/routers/copilot.py`; HTTP/rendering/delivery/FSM adapters under `bot/`; dedicated
`test_case_mentor*`, `test_telegram_*hardening*`, `test_telegram_case_mentor`, and
`test_telegram_operation_lifecycle` suites. Exact commits are listed in Git history
of this task branch; each implementation commit includes its regression tests.

## Implementation matrix

| Task | Status | Finding / fix | Evidence |
| --- | --- | --- | --- |
| BOT-00 | IMPLEMENTED | exact baseline and route map | base archive: 119 passed / 9 DB skips |
| BOT-01 | ALREADY_COVERED + EXTENDED | retained revision/nonce/isolation/backend identity | existing Copilot concurrent updates; new 10 callback dispatcher test |
| BOT-02 | IMPLEMENTED | legacy text/command/duplicate guards; no stale input reuse | FSM/restart/edit-failure and nontext regressions |
| BOT-03 | IMPLEMENTED | no second endpoint after unknown task acceptance; honest Copilot errors | lost acceptance/retry real PostgreSQL; standalone timeout regression |
| BOT-04 | IMPLEMENTED_WITH_LIMITATIONS | responsive truthful controls and owned shutdown | real dispatcher two users; handler/drain/session tests |
| BOT-05 | ALREADY_COVERED + EXTENDED | existing fenced claims; bounded image delivery | real DB delivery suites; RetryAfter/lost ACK/cancel tests |
| BOT-06 | IMPLEMENTED | consumed fresh legacy actions | 10 clicks, stale/new/foreign/restart |
| BOT-07 | IMPLEMENTED | preserve router priority, commands bypass legacy input FSM | actual dispatcher and existing routing matrix |
| BOT-08 | IMPLEMENTED | owner-scoped saved reads, one-shot intentional repeat | history/detail/repeat regressions and HTTP security |
| BOT-09 | IMPLEMENTED | safe malformed/backend errors and truthful uncertain status | HTTP fault cases, no fallback or false success |
| BOT-10 | IMPLEMENTED | safe media helper, all images, failure cleanup | media stream tests, chat/explicit image fakes |
| BOT-11 | IMPLEMENTED | remove early truncation, shared UTF-16 splitting | saved tail sent, Copilot Cyrillic/emoji/markup tests |
| BOT-12 | IMPLEMENTED | actor/route checks, no external credential forwarding | HTTP ownership suites + foreign mentor/action callbacks |
| BOT-13 | IMPLEMENTED | explicit next steps, complete results, safe errors | deterministic user text assertions; manual live UX not run |
| BOT-14 | VERIFIED | full offline tests, real PostgreSQL/Redis and remote container CI | 4174 local tests passed; Python and container-smoke CI passed |
| BOT-15 | IMPLEMENTED | baseline/report/runbook and Draft PR | final delivery metadata below |
| BOT-16 | IMPLEMENTED_WITH_LIMITATIONS | opt-in saved case explanations/questions/reported feedback | semantic grounding, 10 HTTP requests/one artifact, restart+Telegram E2E |

## BOT-16 contract and Mentor audit

Fixed `MarketingExecutors` Mentor still explains saved analysis+creative decisions;
it is retained unchanged. Existing graph VIRTUAL_CMO results already persist
diagnosis, choices, tradeoffs, confidence, evidence/ancestor claims, assumptions,
risks and experiments, but previously had no explicit explanation/replay interface.
Other synchronous modules and legacy results do not automatically gain mentorship.

New owner-authenticated endpoints:

- POST `/copilot/runs/{64hex}/mentor`: create/replay explanation.
- GET the same path: saved explanation only, 404 if absent.
- POST `.../mentor/questions`: bounded question plus stable `request_key`.
- POST `.../mentor/feedback`: explicit outcome, notes and optional reported metrics.

The eight sections are goal, inputs, principle, rationale, alternatives, limitations,
verification and takeaway. They quote accepted business context/decisions and
ancestor assertions, preserving claim type/confidence. No hidden model reasoning
is reconstructed, no source fabricated, and missing economic/comparison evidence
is labeled. Experiments distinguish expected signals from actual observations.

A source-run row lock serializes writes; existing MarketingRun/MarketingArtifact
store a deterministic `case_mentor.v1` companion grouping, not an execution workflow.
Source graph artifacts, jobs and timestamps remain unchanged. Existing graph/fixed
run lists filter their workflow type, so companions do not appear as runnable
projects. Schema and original graph artifact namespace remain unchanged.

There are zero provider calls, including first explanation. Concurrent initial
requests save one artifact; repeats/restarts return the same saved response.
Question/feedback identities replay matching content and reject key/payload conflicts.
Failure rolls back without destroying the original strategy. Provider outage is
therefore not an explanation dependency; database failure is tested instead.

Followups select relevant saved sections and any explicit user-reported feedback.
They do not invent a comparison of a new channel/budget/audience. Reports are not
independently verified causal evidence. BrandProfile is never updated automatically.
Cross-case learning, future-strategy feedback ingestion, project-defense scoring
and individualized learning programs remain followups requiring a separate scoped
context contract. This implementation does not change LLM weights or prompts.

## Verification

All tests use fake providers/Telegram; native PostgreSQL 15.19 on isolated port
55482 and isolated Redis on port 55483. Two explicitly disposable database names
contain `smm_mvp_test` / `durable_job_test`. No production credentials/data used.

- Baseline exact master archive: 119 passed, 9 skipped, 4 warnings.
- Initial real Telegram PostgreSQL/release run: 10 passed, 1 failed because error
  wording intentionally changed; assertion updated to require acceptance uncertainty
  and `/copilot_runs`, while preserving duplicate-job/recovery assertions.
- New root lifecycle/mentor/media/flow focused regressions: 53 passed, 1 warning.
- Existing/new bot/security suites: 195 passed, 2 DB skips, 4 warnings (separate run;
  these skips are not counted as integration evidence).
- Mentor/Copilot API/fixed MVP database compatibility: 98 passed.
- Mentor Telegram→HTTP→PostgreSQL E2E: 2 passed, 51 existing deprecation warnings.
- Mandatory individual commands: `test_telegram_copilot.py` 117 passed;
  `test_telegram_copilot_postgresql.py` 7 passed; `test_release_telegram.py` 4 passed.
- `python -m alembic upgrade head`: PASS on the disposable mentor database.
  `python -m alembic check`: PASS, no new upgrade operations detected.
- `python -m compileall -q app bot`: PASS. `git diff --check`: PASS.
- Full-run import guard initially rejected the new backend reader; its explicit
  service allowlist now includes CaseMentor, while Telegram/runtime boundaries
  remain guarded and source-job immutability is verified by PostgreSQL tests.
- Historical full-run logs reproduced a flaky provider-timeout test whose 50ms
  budget expired during database loading. The provider test now arms its real
  deadline when that provider is entered; a separate real execution-budget test
  proves timeout during durable context loading returns 503 without provider,
  graph or queue work. Both tests passed; five-second HTTP watchdogs retained.
- Frozen full suite on `27c3202`: **4174 passed, 0 failed, 0 skipped**, 2037
  existing deprecation warnings, 398.96s. Command: `python -m pytest -q
  --basetemp .tmp-frozen-release --junitxml=.../telegram-release.xml`.
- Subsequent change only clarifies that an unconfirmed feedback ACK may already
  have saved; 11 focused case/lifecycle tests passed. The preceding 13-test
  case/lifecycle/HTTP-PostgreSQL regression run also passed.

An intermediate full run reported 4168 passed / 3 failed. One failure was the
second explicit backend presentation-import allowlist, subsequently fixed and
verified in the 166-test boundary/lifecycle run. Two global drain-count assertions
encountered a leftover running graph job from an interrupted test process (SQL
confirmed one running graph job). The final full run uses two newly created empty
disposable databases, rather than clearing shared data or weakening drain assertions.

A subsequent run reported 4170 passed / 2 failed. The owner-transaction probe in
the existing task finalization test used NOWAIT while a legitimate contender could
briefly hold that row; a bounded two-second real lock acquisition now distinguishes
contention from an owner leak. The explicit owner transaction assertion, claim
token, ten-second watchdog, exactly one persisted Task and provider/replay counts
remain unchanged (24 related tests passed; independently reviewed). The other
failure came from an older already-collected lifecycle fake while its shutdown
implementation was being updated; the frozen final run avoids mixed source
versions. This is why in-progress runs are not reported as final success.

Docker container smoke, SIGTERM and recreation: NOT_RUN locally; Docker daemon
pipe absent. Existing CI already runs full DB/Redis tests, migrations and container
smoke. CI steps/assertions were not weakened. Live Telegram/provider acceptance:
NOT_RUN by design; requires separate operator-run verification.

### Required scenario mapping

| Scenarios | Executable evidence |
| --- | --- |
| E2E-01,03,04,08,21,22,23 | test_telegram_copilot: direct/delegation, stale keyboards, ledger, cancellation, status and real dispatcher |
| E2E-02 | test_telegram_hardening_flows::test_actual_dispatcher_ten_url_callbacks_execute_once |
| E2E-05,06 | test_release_hardening_postgresql timeout-before-provider/provider tests; test_release_telegram acceptance-before-timeout |
| E2E-07,13 | test_release_telegram restart list/result; test_telegram_copilot_postgresql persisted accepted artifacts |
| E2E-09,20 | test_telegram_operation_lifecycle: two actors during pending request; owned update/delivery drain |
| E2E-10 | test_http_security; foreign legacy actions; mentor HTTP/Telegram owner denial |
| E2E-11,12 | test_telegram_hardening_flows action/repeat concurrent, stale, restart and modified-agent tests |
| E2E-14,15 | test_telegram_copilot error envelopes; backend malformed-response/media hardening tests |
| E2E-16 | chat all-images/failure and explicit image FSM regressions with fake HTTP/Telegram |
| E2E-17,18 | test_telegram_media_delivery_hardening current-token ACK, RetryAfter, lost ACK and cancel; existing real DB workflow delivery tests |
| E2E-19 | Copilot UTF-16 splitter and legacy detailed-tail preservation tests |
| E2E-24 | real DB multi-worker graph/delivery claims and ten mentor HTTP callers; multiple real Telegram pollers deliberately unsupported |

These establish offline scenario correctness; process-container recreation and
real Telegram transport remain separately NOT_VERIFIED locally.

| Mentor scenario | Evidence / supported limit |
| --- | --- |
| MENTOR-01 | Telegram explanation E2E creates strategy, completes worker, opens saved eight-section explanation |
| MENTOR-02 | same-case alternative-channel question includes original goal/choices and explicit lack of new comparison data |
| MENTOR-03 | semantic test requires missing economics/experiment caveats; no invented source basis |
| MENTOR-04 | fresh API composition + empty FSM reopens same callback with zero provider calls |
| MENTOR-05 | ten concurrent HTTP POSTs return identical payload and one persisted explanation |
| MENTOR-06 | foreign HTTP routes and Telegram callback denied without case text |
| MENTOR-07 | explicit reported metrics appear as user-reported, distinct from expected experiment signal |
| MENTOR-08 | subsequent request uses same run and stored reported feedback |
| MENTOR-09 | unavailable-provider composition remains usable; injected explanation write failure rolls back, source still readable |
| MENTOR-10 | semantic assertions match saved business goal, product, exact recommendation and ancestor support; eight named sections and expected-vs-actual checks |

Implementation commits: `d1c9f5a` (main behavior), `2fcc781` (validation/CI),
`9e0e373` (pre-middleware shutdown ownership), `3cec824` (strict Mentor ACKs),
`27c3202` (deterministic transaction probe). No prior unrelated working-tree files
are included. The frozen full release suite targets `27c3202`.

## Remote CI evidence

[CI run 228](https://github.com/Pickle-Pee/smm_ai_helper/actions/runs/39693941922)
completed successfully for published code/documentation head `a44e6fb5ee2db62859273e258866a328f9121809`.
The `python` job passed compileall, migrations, schema check and the full suite.
`container-smoke` passed built-image PostgreSQL/Redis tests, app container recreation,
worker lane/Redis recovery/graceful shutdown and active graph SIGTERM/restart.
The subsequent report-only commit records this evidence without changing runtime.

## Final acceptance gates

Gates below include executed local checks and successful remote CI. Live provider
quality remains an explicit operator gate; this report does not authorize deployment.

| Gate | Status | Evidence / limit |
| --- | --- | --- |
| 01 Functional correctness | PASS | all 4174 offline tests pass, including real DB critical flows |
| 02 Concurrency | PASS | actual dispatcher duplicates, real PostgreSQL graph/mentor locking |
| 03 Recovery | PASS | saved graph/mentor restart and acceptance-before-ACK tests |
| 04 Delivery | PASS | ACK/cancel/RetryAfter, actual DB claims/leases and saved recovery; visible delivery remains at-least-once |
| 05 Security | PASS | source ownership/clicking actor, task/action checks, media origin tests |
| 06 Errors | PASS | malformed/provider/backend/Telegram faults; no false success |
| 07 Compatibility | PASS | full standalone/fixed MVP/Copilot/graph/database/Redis suites pass |
| 08 Tests | PASS | local checks plus successful Python/container-smoke CI on a44e6fb; migrations, recreation, shutdown and SIGTERM recovery passed |
| 09 Documentation | PASS | baseline, this report, operational runbook |
| 10 Reviewability | PASS | independent review fixes applied, logical commits complete; Draft PR #129 published and attached |
| 11 BOT-16 | PASS | saved accepted strategy explanation and Telegram/HTTP/DB tests |

Verdict: **READY_WITH_LIMITATIONS**. Required local checks and remote container
recreation/SIGTERM recovery pass. Live provider/Telegram quality still requires
operator acceptance; counterfactual synthesis and cross-case learning remain
explicit limitations. The PR stays Draft. Test success does not authorize deployment.
Known guarantees: idempotent graph acceptance and mentor
artifact creation; recoverable at-least-once Telegram delivery; no exactly-once
provider execution or visible-message delivery guarantee.
