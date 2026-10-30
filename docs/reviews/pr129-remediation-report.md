# PR #129 remediation — 2026-10-22

Candidate before remediation: `72ac2bb17ca33a5e0891a3abdf3d88a069d32999`.
Base and merge base: `a51a12d44da602d96a22cb99e26026898c8006a2` (`master`).
Existing [Draft PR #129](https://github.com/Pickle-Pee/smm_ai_helper/pull/129)
and branch `codex/telegram-production-hardening` are retained.

The independent audit is available locally at
`C:/Develop/smm_ai_helper/docs/reviews/pr129-independent-acceptance-audit.md`.
Its 309 requirement rows, including BOT-00, are the input to final acceptance.
No missing historical requirements or diagnostic logs have been reconstructed.

## Reproduction and environment

The exact original audit diagnostics ran against the unchanged exported candidate:
**25 passed**, 50 warnings, 7.41 seconds. These assertions intentionally expect
the defects: this result confirms reproduction, not acceptance. The original
diagnostic source remains at `.audit/pr129/tests/test_pr129_independent_audit.py`.
The positive fault/routing/delivery probes are retained without weaker assertions
in `tests/test_pr129_acceptance.py`; defect probes are replaced by explicit
regressions in the corresponding remediation suites.

The original working directory and existing PR checkout were preserved. An isolated
local clone under `.worktrees/pr129-remediation` tracks the same remote PR branch.
Fresh PostgreSQL 15 on loopback port 55449 and Redis on 56399 use only synthetic
credentials. Databases are `smm_mvp_test_pr129_remediation` and
`durable_job_test_pr129_remediation`. External model endpoints point to
`http://127.0.0.1:9`; Telegram and models are fake. Evidence and the complete
environment-setting command are in
`C:/Develop/smm_ai_helper/.audit/remediation/run-tests.ps1`.

Local Docker is unavailable: the `dockerDesktopLinuxEngine` named pipe is absent.
Container execution must be verified by CI on the published remediation revision.
No production data or secrets are changed. Existing migrations run only on disposable databases. No deployment or merge is performed.

## Root causes

| Finding | Reproduced failure | Root cause | Required regression |
| --- | --- | --- | --- |
| F1 | Audience and budget questions return identical paragraphs | Question handler selects stored sections using keywords and has no model capability | Five distinct contextual questions through an injected model; prompt/response semantic contracts |
| F2 | Prior-only segment absent from next answer; history GET returns 405 | Saved question artifacts are never loaded into response context | Ordered owner/case-scoped history, restart, referential follow-up and isolation |
| F3 | 15000/30/3 feedback produces no derived metrics | Feedback persists raw text only | Validated deterministic cost/conversion calculations and explicit ambiguity handling |
| F4 | Same payload/key calls provider twice after lost response | Persisted interpretation is mistaken for persisted execution response | Committed result replay, ten contenders, changed payload conflict, restart, ambiguity |
| F5 | All gates/BOT16 declared PASS despite absent dialogue | Structural and persistence evidence is treated as semantic product acceptance | Requirement-level matrix with separate engineering, product and live gates |
| F6 | Successful `{}` workflow response raises KeyError | Fixed workflow renderer indexes unvalidated fields | Missing/unknown/wrong-type run/status/artifact/media/delivery shapes safely rejected |
| R1 | 1500 inactive actors remain in memory | Ephemeral action mapping has no age/capacity policy | TTL, bounded actors/actions, one-shot, eviction, ownership, stale callback rejection |

## Verification plan

| Boundary | Required evidence | Priority |
| --- | --- | --- |
| Mentor context and dialogue | Existing provider/Expert Core composition, accepted evidence only, bounded history, five-question sequence, prior-only segment, source injection labels | P0 |
| Mentor execution | Commit identity before external I/O; no transaction during provider; timeout/failure/restart/concurrent replay and unchanged source artifacts | P0 |
| Feedback | Currency/count/period ambiguity, negative/contradictory values, zero denominator; no unsupported ROI/causal claims | P1 |
| Synchronous execution | Lost response after commit, ten concurrent calls, fingerprint409, owner/restart, finite retention, unknown outcome | P0 |
| Telegram | Strict successful-body validation, safe recovery, bounded actions, actual Dispatcher, full long output | P1 |
| Existing production mechanisms | PostgreSQL rollback/recovery, Redis failure, worker termination/drain, lost delivery ACK, actor ownership | P0 |
| Whole candidate | compileall, complete pytest with both disposable databases and Redis, Alembic upgrade/check, diff review/check, exact-revision CI | P0 |
| Live acceptance | Real model relevance/honesty/injection resistance and real Telegram transport | Separate operator gate; not authorized in this task |

## Implemented remediation

### F1 — Generative case answers

Implementation: `CaseMentorService.question` now invokes the existing
`application_model_call` single-attempt capability with `ExpertInstructionComposer`.
Its instructions require case-specific decisions, conditional alternatives,
marketing principles, critical reconsideration, unknown-data disclosure and a
falsifiable next step. A bounded structured generation contract is validated
before the public answer is committed. No alternate OpenAI client, orchestrator,
worker lane or hidden reasoning source was added.

Files: `app/marketing_copilot/mentor.py`, `mentor_contracts.py`, `production.py`,
`api_service.py`; `app/routers/copilot.py`; `bot/handlers/mentor.py`.
Regressions: `test_case_mentor_dialogue_postgresql::test_dialogue_five_questions_restart_history_isolation_and_metrics`
checks five distinct VK/Telegram/new-audience/budget/measurement replies, actual
business facts and accumulated context. `test_case_mentor` checks trusted
instructions, source data labels, bounded context and preservation of later facts.
Limitation: model fixtures establish semantic integration contracts, not live model
quality or a universal absence of hallucinations/injection susceptibility.
Commit: `8426819`; backend integration `117b2c4`.

### F2 — Persistent dialogue and restart

Implementation: ordered user/assistant turns live in existing MarketingArtifact
records scoped by source run and authenticated owner. Context reads the latest
12 turns; GET `.../mentor/questions` and `/case_history` read up to 50 saved turns.
Reopening a case restores the continuation path after FSM restart. No cross-case
or cross-user history is loaded. A duplicate completed request key replays the
answer, while changed content returns 409.

Files: `mentor.py`, `mentor_contracts.py`, `app/routers/copilot.py`,
`bot/handlers/mentor.py`. Regressions/integration: the dialogue PostgreSQL suite
checks prior-only segments, new backend composition, two contradictory cases,
foreign actors, ten duplicate questions and distinct concurrent questions; the
second generation receives the first committed answer. Existing Telegram/HTTP/SQL
mentor restart coverage is retained with an explicit fake model.
Limitation: the context is intentionally bounded and the read API returns the last
50 turns, not an unlimited transcript export. Older turns remain persisted.
Commit: `8426819`; integration `117b2c4`.

### FIX-03 — Mentor execution lifecycle

Implementation: a committed `case_mentor_execution.v1` artifact identifies each
logical question before model I/O. Short source-row transactions serialize
same-case admission/completion, with a 45-second active ownership window and
token fencing. Different keys wait up to 40 seconds; the model deadline is
30 seconds. The bot POST deadline is 75 seconds. No transaction spans provider
I/O. Saved answers replay; crashed, timed-out, malformed or otherwise unknown
same-key executions fail closed instead of automatically spending again.

Regressions/integration: a held provider permits another transaction to acquire
the source lock, ten callers yield one generation, distinct keys serialize in
history order, actual timeout cancels the provider await, malformed model output
is rejected and restarted compositions do not reissue uncertain questions.
The original strategy/artifacts/jobs remain unchanged.
Limitation: an external provider's unknown outcome cannot be resolved universally;
same-key automatic recovery deliberately does not regenerate. A new question is
new work and may generate after the active case ownership expires.
Commits: `8426819`, bot timeout in `da196ec`.

### F3 — Reported experiment metrics

Implementation: `mentor_metrics.py` uses bounded Decimal arithmetic over explicit
spend/currency, lead count, sale count and a shared reporting period. It rejects
negative, ambiguous, duplicate, contradictory, malformed-grouped and oversized
inputs. Missing period/currency prompts clarification; zero denominators remain
undefined. Reports and calculations are explicitly user-reported and do not
establish ROI/causality. Saved hypotheses, feedback and validated calculations
are supplied to the next same-case model context.

Files: `mentor_metrics.py`, `mentor.py`, `mentor_contracts.py`,
`bot/handlers/mentor.py`. Unit regressions cover 15000 RUB/30/3 → 500 RUB,
5000 RUB and 10%, missing units/period, multiple periods, malformed/negative/
extreme counts and zero denominators. The dialogue PostgreSQL test saves a report
and verifies that a restarted follow-up receives and uses its calculations.
Limitation: free prose is not guessed into numeric facts. Unsupported metric
formats require a labelled report. Experiment interpretation is a model-quality
operator gate in addition to the tested input/response integration.
Commit: `8426819`.

### F4 — Completed synchronous execution replay

Implementation: `ExecutionStore` reuses MarketingRun with workflow type
`copilot_execution.v1`, separate from graph runs. Owner/key identity and the
fingerprint of supplied fields distinguish operations. Admission commits before
external work; a token fences response persistence. Completed matching calls
return the saved public DTO after lost HTTP responses and composition restart.
Changed running/completed payloads return 409. Unchanged clarification receipts
validate the authoritative interpretation without repeating source acquisition;
only NEEDS_INPUT permits changed clarification content. Unknown outcomes are never
automatically stolen or regenerated. Read-only GET `/copilot/executions/{key}`
and `/copilot_result KEY` restore saved results after FSM loss.

Files: `execution_store.py`, `api_service.py`, `app/routers/copilot.py`,
`bot/copilot_client.py`, `bot/copilot_flow.py`, `bot/handlers/copilot.py`.
Regressions/integration: `test_copilot_sync_replay_postgresql` verifies lost response,
ten contenders, model call count 1, DIRECT_RESULT, restart, payload conflict,
ownership, unlocked committed receipt during provider execution, timeout ambiguity,
crashed pending claim and retention expiry. The Telegram recovery suite exercises
the real Dispatcher with fresh FSM and GET-only recovery.
Limitation: receipts expire after 30 days; deletion is opportunistic on admission,
and expired keys must not be reused. CONVERSATION receipts preserve delegation,
not the legacy chat reply. Initial `/tasks/start` and legacy chat lack the same
request identity; existing standalone continuation replay remains intact. These
broad legacy repeat requirements remain PARTIAL rather than falsely claimed PASS.
Commits: `117b2c4`, clarification validation regression fix `ef0d218`.

### F6 — Strict fixed-workflow response boundary

Implementation: shared wire validation checks complete status responses, allowed
statuses, artifacts and typed nested results, identity coherence, images, job
summaries and delivery metadata before rendering. Completed/awaiting states require
their corresponding saved artifact. Both the HTTP boundary and renderer fail safely;
no global Exception catch hides programming failures and malformed data never
becomes false COMPLETED.

Files: `bot/workflow_contracts.py`, `bot/backend.py`, `bot/handlers/workflow.py`.
Regressions: `test_telegram_remediation` covers absent fields, list vs object,
unknown status, wrong nested types, malformed media/delivery, successful valid
rendering and the actual Dispatcher. Existing architecture boundary checks remain
enabled; the wire summary class is named WorkflowJobSummary to distinguish it
from forbidden internal Job contracts.
Commit: `da196ec`; integration boundary correction `ef0d218`.

### R1 — Bounded ephemeral actions

Implementation: 1000 actors maximum, 10 actions per actor, 4000 characters per
action, absolute 15-minute monotonic TTL. Creation/consumption prunes expired
entries; new keyboards replace the actor's prior tokens; capacity evicts the
oldest keyboard. Tokens are consumed before awaiting HTTP. Metadata is removed
with the final consumed entry. Restart/expiry/eviction fail closed and identical
text receives a new random identity.

Files: `bot/handlers/chat.py`. Regressions: 1500 actors remain capped, oversized
actions rejected, expiry at the exact deadline, no old-token revival, ten
concurrent consumers call once, foreign actor/evicted callback never executes.
Limitation: this is a process-local convenience for the documented single-poller
deployment, not a durable action service.
Commit: `da196ec`.

### F5 — Honest release evidence

Implementation: README, architecture, UX, runbook and hardening report now describe
generated dialogue, saved history, numeric-report limits, receipt recovery and
legacy boundaries. The former all-PASS/READY claim is withdrawn. The accompanying
matrix retains every one of the 309 provided requirement rows, with implementation,
test, observation, status and limitation columns. Engineering reliability, semantic
fixture contracts and live acceptance are explicitly distinct.

Limitation: no live OpenAI/Telegram call, production deployment or merge was
authorized or executed. Local Docker remains unavailable; current-head remote CI
must supply container evidence. Documentation commit is identifiable in Git history.

## Validation history and review

- Original independent diagnostic reproduction: 25 passed (defects expected).
- Telegram final targeted run: 237 passed, 7.71 seconds.
- Replay API/PostgreSQL targeted run: 111 passed, 26.67 seconds.
- Replay Telegram targeted run: 126 passed, 6.70 seconds.
- Mentor PostgreSQL/HTTP/UI targeted run: 25 passed, 15.85 seconds; final units:
  22 passed, 5.26 seconds. Later timeout/concurrent assertions are included in the
  final full suite and the 70-test integration repair run.
- First expanded acceptance run: 64 passed, 3 failed because old Telegram SQL
  assertions prohibited any MarketingRun; revised assertions require exactly one
  completed receipt and still forbid graph starts.
- First full candidate: 4263 passed, 5 failed, 1 setup error, 431.70 seconds.
  The pending receipt masked corrupt interpretation validation (fixed without
  acquisition replay). Other failures came from the old graph-run count, a
  synthetic action fixture missing TTL metadata, a wire DTO named Job triggering
  the architecture guard, and a removed pytest fixture import. No production
  checks or detector assertions were disabled. The graph tests now assert one
  graph plus one completed receipt, and the action owner test creates a real
  keyboard. Both independently observed actor identity assertions remain.
- Final focused integration repair: **70 passed**, 952 warnings, 40.28 seconds.
  Includes corrupt interpretation, ten pending-clarification callers with one acquisition,
  all retained audit positives, new dialogue/concurrency, recovery and security.
- compileall and Alembic upgrade/check: PASS on disposable PostgreSQL; no new
  upgrade operations detected. `git diff --check`: PASS.

The Telegram boundary diff was reviewed independently; Mentor review found the
10-second bot deadline and whole-section clipping risks, both fixed and covered.
Replay review confirmed transaction boundaries, ownership, fencing and honest
legacy limitations. A later review identified duplicate pending acquisition under
the initial interpretation fix; explicit authoritative validation plus saved
clarification replay removed that waste and has a ten-caller regression.

Logs retain unsuccessful and successful runs at
`C:/Develop/smm_ai_helper/.audit/remediation/`.

## Frozen final verification

Frozen runtime/test revision: `ef0d218211105b3d8d9f9735774983ea53b7fa79`.
The following report/documentation commit changes no runtime or tests.

- Final local full suite: **4270 passed, 0 failed, 0 errors, 0 skipped**;
  2985 deprecation warnings, 515.13 seconds. Two newly created empty disposable
  databases with suffix `_remediation_full2` were used. Evidence: `full.log` and
  `full.xml`; command: `.audit/remediation/run-tests.ps1 full` (sets synthetic
  environment then runs `python -m pytest -q`). Net test expansion vs audited
  baseline: 96 additional collected cases, without disabling existing cases.
- `python -m compileall -q app bot`, `python -m alembic upgrade head`,
  `python -m alembic check` and `git diff --check`: PASS. Alembic detected no new
  operations. These checks were repeated after final runtime changes.
- Current one-shot mutant: restoring a consumed token and its TTL in process
  causes the unchanged regression to fail `10 != 1`. Current owner mutant:
  bypassing the actor scope causes the unchanged foreign-access assertion to fail
  `200 != 404`. Both wrappers exit successfully only when that expected invariant
  failure is detected. No tracked source is mutated. See `mutation-action.log`,
  `mutation-owner.log` and `mutation_probe.py` in the evidence folder.
- [CI run 231](https://github.com/Pickle-Pee/smm_ai_helper/actions/runs/39786141612)
  completed successfully for the frozen runtime revision. Python 3.11:
  **4270 passed**, 1327 warnings, 283.34 seconds. The Python job also ran compile,
  migrations and schema check. Container smoke: **581 passed**, 520 warnings,
  110.12 seconds, followed by successful persistence/recreation, both worker lanes,
  Redis outage/recovery, drain/pause, active/idle worker SIGTERM, backend recreation
  and bot SIGTERM/restart checks with external providers disabled.
- CI checked out merge commit `18a368cd6f0998ea7f2b16f4e14e068085fba058`.
  `git diff --quiet CI_CHECKOUT ef0d218...` returned 0: its tree matches the
  candidate exactly. Latest documentation-only PR head receives its own CI run;
  the final PR summary records that published head/check rather than assuming it.

## Pull request summary and verdict

PR: <https://github.com/Pickle-Pee/smm_ai_helper/pull/129>, remains Draft.
Base SHA: `a51a12d44da602d96a22cb99e26026898c8006a2`.
Published final head SHA is recorded in the PR description after this report is
committed. Runtime SHA and CI checkout SHA are fixed above.

Remediation commits:

- `da196ec` — fixed-workflow validation, bounded actions and Mentor HTTP timeout.
- `8426819` — generated case dialogue, history, execution fencing and metrics.
- `117b2c4` — completed execution replay and saved-result recovery.
- `c36e26f` — retained independent probes and new container acceptance gates.
- `ef0d218` — preserve interpretation/security/architecture integration invariants.
- The subsequent documentation commit — coherent release evidence and the
  requirement-level matrix.

Changed files are the task-only diff against `72ac2bb`; the complete list is
available in the PR diff/Git history. Migrations added: **none**. New dedicated
suites: `test_case_mentor_dialogue_postgresql`, `test_copilot_sync_replay_postgresql`,
`test_telegram_remediation`, `test_telegram_sync_recovery`, `test_pr129_acceptance`.
Existing Mentor, API, actor-security and graph-count tests retain their behavioral
assertions and explicitly account for receipts.

Original F1–F6/R1 findings are remediated within the tested backend/interface
contracts. Broad legacy initial-start replay, active backend cancellation,
unbounded transcript export, exhaustive presentation maxima and live semantic
quality are not claimed as implemented/proven. The matrix records their exact
status instead of substituting them for the required generative Mentor.

Release verdict: **READY_WITH_LIMITATIONS**. The AI dialogue mechanism, persisted
memory, metrics pipeline and completed Copilot replay are present and exercised.
Live provider judgment and real Telegram transport remain separate authorized
operator gates. This verdict does not authorize merge or deployment.
