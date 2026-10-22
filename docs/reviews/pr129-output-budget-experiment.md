# PR #129 — POSITIONING output-budget experiment

Date: 2026-10-23 (Europe/Moscow). **EXPERIMENT_FAILED**.

One real generation with `max_output_tokens=128000` returned HTTP 200 but `status=incomplete`, reason `max_output_tokens`, an empty output array and numeric zero input/output/reasoning usage. A read-only GET independently confirmed the stored envelope. No 32K/64K generation or 128K repetition was performed. The required successful full POSITIONING was not obtained.

## Source and previous evidence

- Original PR #129 head, independently reconfirmed: `b04685bc586845592f509eababc5388672852926`; base `master`; open branch `codex/telegram-production-hardening`.
- Historical staging candidate: `250d1ea3338724ff10593763ed9485c8476d1d4a`.
- Exact application/runner source for the real 128K call: **`ec8e74183d0a5c87d42f1fe5593d2d7731e11f0b`**. This is the historical staging candidate plus isolated experimental policy/tooling. Later changes add diagnostic/test/report tooling; they do not change the generation's application code.
- Experiment branch: `codex/pr129-output-budget-experiment`, in a separate managed worktree. Existing working-copy modifications were preserved.
- Fetched `origin/master` and deployed production SHA: `a51a12d44da602d96a22cb99e26026898c8006a2`. No old implementation branches were merged.

Read `pr129-server-live-e2e.md` and `pr129-live-e2e-preflight.md` from the retained `.worktrees/pr129-live-preflight/docs/reviews/` copy, and `docs/reviews/pr129-positioning-live-failure-rca.md`. Those reports' old spending permission was not reused as authorization for this campaign.

The historical 16K incident was HTTP 200, `incomplete/max_output_tokens`, zero output items and numeric zero usage in 1.577 seconds, resolved model `gpt-5-mini-2025-08-07`. IDs:

- Request: `req_211f2e454a154e5cae808456ab1a5f7e`.
- Response: `resp_0a42e979ac2d9353006ada2978b4c887d28b73d166f4055337`.

This is a historical observation from another campaign, not a repeated controlled baseline measurement.

## Model, pricing, rate limits and spending authorization

The fetched [official model documentation](https://developers.openai.com/api/docs/models/gpt-5-mini) lists 400000 context, 128000 maximum output, structured outputs, and Standard text prices of $0.25/M input, $0.025/M cached input and $2/M output. The requested model alias was retained; no model migration occurred. Authenticated `GET /v1/models/gpt-5-mini` returned 200 with `shutdown_date=null`.

Project-specific TPM/RPM limits and output-reservation accounting could not be obtained from the ordinary key's model metadata. Neither the model lookup nor generation exposed rate-limit headers. No administrative project/billing credential was available. The actual 128K request was accepted at HTTP level without 429; that does not establish spare project capacity or explain the incomplete envelope. [Official rate-limit guidance](https://developers.openai.com/api/docs/guides/rate-limits) remains relevant to reservation planning, but no project limit is inferred from public model capabilities.

The original task required confirmed external spending control. During this chat the user explicitly changed that condition: no external control exists, use the same key and do not worry about the balance. Paid execution proceeded under that updated authorization. No external dollar cap is claimed. The application ledger controls attempts, not account charges.

At the final independently counted input of 12026 tokens, assuming uncached Standard text pricing:

| Planned profile | Upper token-price estimate |
| --- | ---: |
| 128000 | $0.2590065 |
| 32000 | $0.0670065 |
| 64000 | $0.1310065 |
| Planned campaign total | **$0.4570195** |

These estimates exclude taxes and unrelated account traffic; reasoning is included in output and is not added again. The broad three-calls-at-128K bound would be $0.7770195, also below the requested $2 estimate ceiling. Actual campaign: **1 generation POST, provider-reported 0 input / 0 output / 0 reasoning / 0 cached tokens; usage-derived estimate $0**. Confirmed Billing charges: **unavailable**, not proven zero.

## Input restoration and token counting

The original raw HTTP request body was not preserved. This is a measured reconstruction, not a claim of historical byte identity. The saved compiled Stretch Point plan, exact source, original Expert Core, specialization, response mode, local evidence preimages, missing business seeds and all 16 expected outputs were restored. No business facts, model effort, output fields or validator rules were changed.

The actual executor matched the reconstruction's instructions and schema, and matched the input's parsed JSON values. Its JSON object key ordering differed from the previous RCA helper; both versions were retained privately. No arrays or values changed. Runtime input SHA-256: `95bdf43e58750c186ea5fb69e1a3ae3b4c489ce18b70712b5c93d40e996f9f6c`. Earlier reconstruction input SHA-256: `dc2ac302e0deebab9638d3c4fddf3b6bff5b704acda49e2f67fed027b1d33f22`.

| Payload component | Verified measurement |
| --- | --- |
| Composed system instruction | 53151 UTF-8 bytes |
| Serialized module input | 9893 UTF-8 bytes |
| Original compact schema | 7709 bytes |
| Schema canonical SHA-256 | `d0e0361566b1adb9b1ef59136713914f55d2f39675f206734068259bfffeb277` |
| Expected unique outputs / local evidence / parent claims | 16 / 8 / 0 |
| Reasoning effort | `low` |
| Schema projection / product-support wire | false / false |

Before generation, `POST /v1/responses/input_tokens` received equivalent `model`, `input`, `text.format` and `reasoning`, following the [official counting endpoint](https://developers.openai.com/api/docs/guides/token-counting). The first helper-order reconstruction counted 12034 tokens. After adopting the real executor's ordering, the final count was **12026**, request ID `req_cf2a384aa37d42a7abd8ae5ec2b1e426`. The 8-token difference is recorded, not hidden. Final context allowance: `400000 - 12026 - 128000 = 259974` tokens of headroom.

Each actual outgoing generation payload was asserted equal to the frozen final request before durable admission or HTTP. Only its configured output cap can vary. There was no auxiliary paid smoke request.

To freeze original evidence IDs, the isolated runner supplies the historical module execution ID `c88e4588fa0d9bbb73a55a9b8d4bbc37` to the original executor as an input-fixture namespace. The real graph job/lease/owner/run are newly created in the new DB; graph telemetry uses that new identity. This diagnostic adapter is confined to the campaign runner. It does not reuse the old durable job, request key, claim, fencing token or ownership. It is an explicit difference from ordinary production execution, where the module execution ID equals the durable job ID.

## Server isolation and execution path

Host: `nl-vmv2-nano`. New directory: `/opt/smm_ai_helper_e2e/output-budget-experiment`. Production `/opt/smm_ai_helper` was inspected read-only and never restarted.

New container `smm-obe-db`, new volume `smm-obe-database`, and new networks `smm-obe-offline` (internal) and `smm-obe-live` were used. No DB port was published. Separate databases on this new PostgreSQL instance:

- `smm_mvp_test_output_budget`: destructive fake-provider regression fixtures only.
- `output_budget_campaign`: durable real experiment state only.

Dependencies reused immutable image `sha256:389f1c45b0fc7b46f5b59b9a371057227d4abd0ab68bf078ce409c0cacfee8c7`; archived experimental source was mounted read-only at `/workspace`. No image build or production replacement occurred. DB limits: 256 MiB, 0.5 CPU, 128 PIDs. Runner: 768 MiB, 1 CPU, 256 PIDs, read-only root and bounded tmpfs. Live calls ran one at a time. No Telegram poller or whole marketing graph was launched.

The single-module compiled plan uses `explicit_single_module_v1`. Execution proceeds through PostgreSQL graph start/claim → real `ModuleGraphWorker` → dispatcher → original `PositioningExecutor` → production model adapter → Responses transport with committed admission → original schema/business validation → Quality Gates → fenced graph persistence. No separate generator or relaxed validator was introduced.

Before setup: approximately 2868 MiB available RAM, 0 swap used, 45 GiB free disk; production backend/DB/Redis healthy, worker/bot running. A later regression sample had 2690 MiB available, 0 swap used and 45 GiB free. These are snapshots, not continuous peak measurements.

## Experimental policy and timeout configuration

`POSITIONING_OUTPUT_BUDGET_EXPERIMENT` is an internal optional setting with the closed values 16000/32000/64000/128000; default `None`. Its env parser accepts exactly those numeric strings. Enabling it requires controlled staging, the requested `gpt-5-mini`, official base URL, zero transport retries, and disabled POSITIONING schema/wire feature flags. It changes only the `POSITIONING_FULL` capability's cap; arbitrary numeric requests retain the generic 4K cap. No public DTO or persisted schema changed.

The old controlled ledger stays `controlled_live_e2e_v1`. New ledger: `positioning_output_budget_20261023_v1`. Admission accepts only POSITIONING graph calls with low effort, strict original schema fingerprint, bounded payload and the selected cap. It serializes committed reservations, allows at most three distinct profiles in order 128K → 32K → 64K, blocks repeats, and blocks the campaign after any rejected/uncertain response. 16K remains historical and is not admitted as another paid baseline in this campaign. Different new durable runs are permitted only for this experiment.

HTTP timeout 600 s < graph execution timeout 780 s < durable lease 900 s. Pydantic and worker constructors accepted this finite chain. These settings were prepared for all comparison profiles, although only 128K ran. Production defaults, graph retries, legacy transport semantics and feature flags remain unchanged when the experiment is disabled.

## Actual results and comparison

**Configured max output is not actual output consumption.** Input token-count preflight is also distinct from provider-reported generation usage.

| Configured cap | HTTP accepted? | Provider status | Reported input | Reported output | Reasoning | Visible output / JSON bytes | Duration | Usage-price estimate | Schema valid? | Semantics valid? | Quality accepted? |
| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | --- | --- | --- |
| 16000 historical | 200 | incomplete/max_output_tokens | 0 | 0 | 0 | 0 / 0 | 1.577 s | $0 reported-usage basis | Not evaluated | Not evaluated | Not evaluated |
| **128000** | **200** | **incomplete/max_output_tokens** | **0** | **0** | **0** | **0 / 0** | **2.298 s observed wrapper; 2.242 s transport** | **$0 reported-usage basis** | Not evaluated | Not evaluated | Not evaluated |
| 32000 | Not sent | Stopped after A anomaly | — | — | — | — | — | — | — | — | — |
| 64000 | Not sent | Stopped after A anomaly | — | — | — | — | — | — | — | — | — |

The 128K response reports cached tokens=0, total tokens=0 and output items=0. JSON bytes above mean generated JSON, not the nonempty provider envelope saved privately. Reported output/cap fraction is 0%; no true consumption or needed budget can be inferred from anomalous zero metering.

Separate acceptance axes:

```text
TRANSPORT_ACCEPTED = false  # HTTP succeeded; completed usable envelope did not
SCHEMA_ACCEPTED    = NOT_EVALUATED
SEMANTICS_ACCEPTED = NOT_EVALUATED
QUALITY_ACCEPTED   = NOT_EVALUATED
```

No output exists to validate for coverage, duplicates, evidence IDs, HYPOTHESIS/OBSERVATION kinds, product promises, invented uniqueness or missing-seed rules. Those authoritative checks remain installed; none passed on this live response. Marketing usefulness is **NOT_SCORED**, not accepted. There are no accepted campaign artifacts.

New provider IDs:

- Request: `req_9d91440a0c044395939aa855f490e014`.
- Response: `resp_0ab155ea39f8bc9c006ada9a7cc88087d28e9e5e17fa28cea9`.
- Resolved model: `gpt-5-mini-2025-08-07`; service tier `default`.
- Read-only verification GET: HTTP 200, request `req_e56a62540cf0435eb05d19e4deff476e`. Stored `max_output_tokens=128000`, `error=null`, identical numeric zero usage and empty output.

Durable run `obe20261023-128000`; job `1b1a65d99f5b83bb9028ac1cdcc24b81`. Final run/job failed with `controlled_outcome_unknown`, attempts=1, no active lease. That existing label records conservative no-replay disposition; it does not mean the HTTP response was lost. Ledger blocked, calls=1, budgets=[128000], one unknown receipt.

## Regression, defects and review

Server suite against separate PostgreSQL and fake provider covers the changed transport/settings/admission boundaries, old controlled and normal production policies, timeout/crash/replacement/fencing, model adapter, telemetry, POSITIONING output and seed contracts. Initial run: 342 passed / 4 failed because a new Settings test inherited the fake endpoint; corrected by explicitly setting the endpoint. Next run: 346 passed / 0 skipped. After the env-parser correction: 346 passed / 0 skipped. Final extended run adds four 128K no-replay cases; see final validation record below.

The first live-runner process failed during Settings construction: numeric `Literal` profiles did not accept raw env strings. **No admission marker, durable run or generation POST existed at that point.** Fixed with an exact closed-set before validator and regression cases using actual environment strings. No request/model/schema change accompanied that fix.

Additional Windows fake-provider tests: 18 passed / 1 PostgreSQL-only skip for the extended experimental test file. The real PostgreSQL equivalent is included in server validation; the local skip is not counted as a pass.

A fresh application process with a provider-forbidden stub attempted terminal-job replay: no work, attempts still 1, no active lease, ledger still blocked with one receipt/call, zero provider calls. This verifies the real campaign's terminal state across process replacement without regenerating. The replay script initially lacked `/workspace` in Python's import path; the tooling was corrected, with no provider call or state reset.

The full task diff was reviewed separately after implementation: schema/instructions/DTOs/executor/gates unchanged; defaults preserved; ledger reservation committed before provider; finite timeout ordering; no automatic clearing/replay; no secrets in committed tooling/report. No remaining material runtime finding was identified. `git diff --check` and source compilation are recorded in final validation. A complete repository test suite and successful full POSITIONING persistence are not claimed.

## Root-cause implications and production recommendation

**ROOT_CAUSE_UNRESOLVED.** The immediate failure is a provider-returned, persistently stored empty incomplete envelope. The application correctly rejected it. The independent input counter demonstrates a nonempty 12026-token request despite the generation envelope's zero input usage. Raising the cap from the historical 16K observation to 128K did not remove the failure in this reconstructed case.

The result weakens the proposal that simply increasing the configured output budget is a sufficient fix. It does not prove a provider schema/compiler defect, actual budget exhaustion, a transient outage or instruction complexity. These remain hypotheses requiring provider tracing. One nondeterministic sample and a separately reconstructed historical baseline cannot establish a unique cause or the minimum sufficient output budget.

Recommendation: **Variant D — continue investigation of POSITIONING/provider handling before changing production output policy.** Keep current production settings. Do not adopt 128K or adaptive budgets on this evidence. There is no successful quality sample, latency distribution, demonstrated token requirement or measured incomplete probability supporting A/B/C. Even a confirmed Standard cost bound cannot substitute for correctness and usable marketing output.

Send neither customer data nor secrets: prepare a provider-support escalation with both incident request/response IDs, snapshots, schema fingerprint, 53151/9893/7709 byte counts, preflight input=12026, low effort, 128000 cap and the GET-confirmed zero counters. Ask where processing stopped and whether final billing agrees. **No support message was sent.** Any next paid diagnostic or retry needs a separate campaign decision; do not clear this ledger. The original PR's full-live acceptance blocker remains.

## Cleanup and evidence

All campaign scripts and safe diagnostics are retained under `/opt/smm_ai_helper_e2e/output-budget-experiment`; evidence under `evidence/`. Private frozen requests and raw provider envelopes remain in the mode-0700 campaign directory. API keys are excluded from the evidence copied locally and from Git. The temporary new key env file is removed at cleanup. Test containers exit automatically; the new DB is stopped and its volume retained for inspection. Existing E2E containers and databases remain untouched and stopped.

Final health comparison checks production container IDs, image IDs, start times, restart counters and health against baseline, and verifies SHA-256 of all retained old evidence files. No production checkout/config/container mutation, ownership transfer, claim deletion, admission reset, merge or deployment occurred.

Local safe evidence directory: `.audit/pr129-output-budget/`. Reproducible tooling is in `scripts/output_budget_experiment/`. It is a diagnostic campaign, not a production rollout. Setup refuses to silently reuse its existing networks/container; repeat paid modes are denied by exclusive markers and PostgreSQL receipts. A fresh campaign requires deliberate new isolation and identities, not deleting the retained evidence.

Final server regression: **350 passed, 0 skipped, 0 failed in 43.74 seconds**. Final production IDs/images/start times/restarts/health match baseline exactly. All hashed old evidence files are unchanged. New DB stopped; its volume and campaign state retained; temporary new API-key env copy removed. Ledger snapshot succeeded. Paid generation count remains **1**, with **0 automatic retries**.

Source compilation (`compileall` for app, campaign scripts and the experimental test) and `git diff --check` passed. Safe machine-readable results are committed in [pr129-output-budget-evidence](pr129-output-budget-evidence/result-128000.json), including independent input count, stored-response verification, terminal replay, health comparison and JUnit summary. The local safe evidence archive SHA-256 is `8fb56bab4b5a26bd0fd0ca8fd030e896294f3e816bbcf772b945dd74613e75f9`; all 17 source-file hashes were verified after download. Raw prompt/provider payloads and keys are excluded from that archive.
