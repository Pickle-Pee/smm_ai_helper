# Telegram hardening and remediation — 2026-10-22

PR: [#129](https://github.com/Pickle-Pee/smm_ai_helper/pull/129), Draft, base `master`.
Integration base: `a51a12d44da602d96a22cb99e26026898c8006a2`.
Audited candidate: `72ac2bb17ca33a5e0891a3abdf3d88a069d32999`.

The independent audit rejected that candidate: free-question mentorship, dialogue
memory, experiment arithmetic, synchronous result replay and successful-body
validation were incomplete. The earlier report's broad PASS/READY verdict is
withdrawn. Historical green CI on that SHA proves the tests it executed, not the
missing product semantics. See [remediation report](../reviews/pr129-remediation-report.md)
and [requirement-level final acceptance](../reviews/pr129-final-acceptance.md)
for current evidence and verdict.

## Preserved engineering behavior

Telegram delegates to authenticated backend HTTP. PostgreSQL remains authoritative;
Redis is wakeup transport. One polling bot per token owns update and delivery tasks.
Callback nonce/revision/actor guards, graph claims, accepted artifacts, fixed MVP
Mentor, independent durable delivery and worker drain behavior are retained.
Active backend workflows cannot be canceled through the Telegram interface;
`/new` and `/cancel` explain this while execution is active.

Media fetches permit only same-origin backend `/images/*.png`, disable redirects,
limit streaming to 10 MiB and impose a deadline. Long presentation uses UTF-16-safe
plain-text splitting. Delivery can display duplicates after an ambiguous send/ACK;
retrying delivery does not regenerate accepted artifacts.

Fixed-workflow HTTP and render boundaries validate run/status, artifacts, typed
nested result, images, jobs and delivery metadata. Missing or invalid content
returns a controlled error rather than false completion or unhandled indexing.
Legacy suggested actions expire 15 minutes after creation. Storage is bounded to
1000 actors, 10 actions per actor and 4000 characters per action; oldest keyboards
are evicted at capacity. Tokens are actor-scoped and consumed before HTTP awaits.
Restart, a new keyboard, eviction or expiry requires fresh suggestions.

## Copilot execution and recovery contract

`ExecutionStore` commits a `copilot_execution.v1` MarketingRun receipt before
external execution and saves the complete public response. Authenticated owner,
request key and supplied-field fingerprint identify an operation. Completed matching
retries replay without interpretation/provider work, including after process
composition restart. Changed running/completed payloads return 409. NEEDS_INPUT
alone permits the existing clarification payload to evolve under the same key.

Retention is 30 days, with opportunistic expiry on new admission; keys must never
be reused after expiry. GET `/copilot/executions/{request_key}` reads a saved receipt.
`/copilot_result KEY` restores a saved synchronous result. The uncertainty message
shows this command and identity. These receipts are excluded from graph run lists.
Unknown external outcomes remain unavailable rather than being automatically
regenerated; exactly-once provider execution is not promised. A deliberately new
request/key can incur another charge.

A CONVERSATION receipt is only a saved delegation decision. Actual legacy chat
replies and initial standalone task starts have no equivalent request identity;
existing standalone continuation claims/history remain intact. Their uncertainty
messages must not imply that graph history contains these results.

## Case Mentor product contract

Opening `/copilot/runs/{id}/mentor` creates/replays an eight-section explanation
from accepted strategy, business context, evidence, lineage and hypotheses. This
read/projection itself needs no provider call. Original accepted artifacts are
immutable and the fixed MVP Mentor is unchanged.

A new POST `.../mentor/questions` uses the existing single-attempt model transport
and Expert Core. The context contains eight accepted sections (4000 characters
each), up to 12 ordered prior user/assistant turns (prior answers capped at 2000
characters), up to five user reports, trust/provenance labels, truncation metadata
and the current question. Source text and prior dialogue are data, not instructions.
A bounded structured generation schema constrains answer length, focus, used
sections and unknowns. No hidden reasoning or unaccepted raw outputs are used.

A short committed artifact claim serializes logical questions per case; model I/O
occurs outside transactions. Completed same-key questions replay the saved answer.
A crashed/timed-out or otherwise uncertain execution is not automatically reissued.
The next different question can proceed after bounded active ownership expires.
GET `.../mentor/questions` returns the last 50 owner-scoped saved turns; `/case_history`
shows them. Reopen the existing case after bot restart to continue its dialogue.
No other case or actor's history is loaded.

`/case_feedback` saves explicitly user-reported observations. Deterministic Decimal
arithmetic accepts labelled spend/currency, leads, sales and a common reporting
period; ambiguous, negative, contradictory or incomplete values require clarification.
Zero denominators do not produce fabricated metrics. Valid 15000 RUB / 30 / 3 yields
500 RUB per lead,5000 RUB per sale and 10% conversion. These calculations do not prove
ROI or causality and never update BrandProfile or the original strategy automatically.

## Acceptance boundaries

- **Engineering reliability:** deterministic tests and disposable PostgreSQL/Redis
  verify ownership, claims/replay, rollback, restart, delivery, shutdown, validation
  and bounded storage. Exact commands/results are in the remediation report.
- **Product semantics:** fake-model tests inspect the real supplied context and
  require distinct, case-specific alternatives, new assumptions, referential
  follow-up and unknown-data behavior. This proves the integration/response
  contract; it is not a measurement of the deployed model's judgment.
- **Live acceptance:** real model relevance, arithmetic honesty, source-injection
  resistance and actual Telegram transport require separately authorized operator
  verification. No live call, deployment or merge is authorized by this report.

No green structural test alone establishes full product readiness. Each original
requirement receives PASS,PARTIAL,FAIL,NOT_VERIFIED or NOT_APPLICABLE with a stated
evidence boundary in the final acceptance matrix.
