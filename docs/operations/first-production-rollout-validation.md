# Local preparation evidence — 15 October 2026

Scope: first rollout #122/#123, source target
`c23dfb2cfc3cfab7cd34fe6226b67404d7d0c166`. Production access, server build/deploy,
production migration, real Telegram polling and paid provider requests: **not run**.
No app/bot runtime, models, budgets, provider configuration or merged migrations
changed by this preparation.

## P1/P2 revision after REQUEST CHANGES

Reviewed starting head: `3cf90887f169ec07b82ff100bbe6c3b13ff5041c`; base remains
`c23dfb2cfc3cfab7cd34fe6226b67404d7d0c166`. Scope is limited to PR #124.

P1: `collect()` authenticates the trusted package's exact manifest bytes using a
compiled SHA256 pin. It never calls `manifest()`, `git archive`, fetch or checkout.
Actual legacy HEAD/status and image provenance are independent observations.
A real **legacy-only Git repository without the target object** is exercised
through the actual collector argument parser/entrypoint, with controlled Linux/
Docker command responses. It reaches network inventory, retains its real legacy
HEAD and image identity, and returns NO_GO/exit 2. Target tampering, truncation,
newline changes and missing manifest fail closed before inventory.

The earlier `02e59b...` checksum described Windows CRLF working-copy bytes, not
the committed LF manifest. It is retired. The trusted Git/LF package pin is
`13623f5e33013f9bb515c1f049fc0099b44f16b4d61dd60138bab1fa333ee98d`.
The manifest's content in Git is unchanged; a narrow `.gitattributes` rule and
binary manifest stdout make byte identity portable. The real local CLI-generated
file was hashed and matches this pin.

P2: `collect()` always records `operator_unverified`; operator DSN is removed from
all inventory child environments and never sent to `docker exec`. A separate
`operator` command runs only in an approved protected host/venv, outside app
directories/containers. Its isolated interpreter receives only operator/system
environment, not application settings; no DSN arguments/stdin, Docker or app
imports are used. A missing/unavailable protected probe, incomplete/mixed app DB
identities, operator DB mismatch, missing control tables or excess role privileges
remain operator_unverified/NO_GO. Every inventoried running app DB fingerprint
must match; success is only metadata_checked and still NO_GO/exit 2.

Executed final local revision checks:

| Check | Result |
| --- | --- |
| Collector and SQL suite | **30 passed**, 4.58 s; no skips |
| Real collector CLI / legacy-only repository | Real Git HEAD/status, no target object; controlled host/Docker inventory reached; NO_GO/exit 2 |
| Real manifest/collect/operator CLI boundaries | Exact manifest stdout bytes; opt-in refusal; corrupt-manifest STOP; invalid operator credential NO_GO; no raw stderr |
| Secret isolation / redaction | Sentinel DSN absent from Docker args/stdin/env and all stdout/stderr/structured output; arbitrary probe fields discarded |
| Real read-only PostgreSQL / operator CLI | Same DB identity verified; overprivileged disposable owner remains unverified; probes use READ ONLY/ROLLBACK and bounded timeouts |
| Local migration / DDL / Docker restart | **Not run in this revision**; SQL tests use an existing disposable schema, with no migration fixture |
| Production / provider POST | **Not run** |

Exact revision test command:

```text
python -m pytest -q --basetemp=.local-test/rollout/p1p2-final
  --junitxml=.local-test/rollout/p1p2-final.xml
  tests/test_production_rollout_readonly.py
  tests/test_production_rollout_postgresql.py
```

Only the existing disposable loopback PostgreSQL service was used; it is stopped
after validation. Full GitHub CI is required again on the updated PR HEAD:
both `python` (full pytest/schema checks) and `container-smoke` must succeed.
The [PR checks](https://github.com/Pickle-Pee/smm_ai_helper/pull/124/checks)
carry commit-bound results; previous merge/starting-head checks below do not
substitute for the revised HEAD. CI uses its existing disposable service lifecycle,
not production. The handoff reports the final exact HEAD and CI run.

The revision diff was re-reviewed for both findings, credential/process boundaries,
pin trust, CLI failure behavior and secret output. Independent release review
is still required. Production bootstrap and image/role evidence remain NO-GO.

## Initial preparation results (before P1/P2)

Environment: Windows, Python 3.12.14 from existing repository venv; a newly created
disposable PostgreSQL cluster listening only on `127.0.0.1:55439`, database
`smm_mvp_test_rollout`; separate disposable Redis at `127.0.0.1:56389`, DB 15.
Providers use existing fakes/MockTransport; configured fallback provider endpoint
is loopback port 9, not OpenAI. The two temporary local services are stopped after
verification; test data stays under ignored `.local-test/rollout`.

| Executed check | Result |
| --- | --- |
| Fetch and compare origin/master | Matches supplied #123 merge c23dfb2; branch created from that exact source |
| Disposable `alembic upgrade head` | Fresh DB upgraded through 0012 |
| Disposable `alembic check` | No new upgrade operations |
| Drain/lifecycle/production worker/fixed/graph/Redis + real collector SQL | **81 passed**, 63.41 s, no skips |
| Final collector + real SQL + worker CLI + telemetry + graph worker suite | **129 passed**, 6.00 s, no skips |
| Deterministic source manifest | 221 source/build/prompt/migration files; head exactly 20261014_0012; Git-byte equality and Windows autocrlf regression passed |
| Safe collection/error boundaries | Host/path/explicit opt-in rejection, fake full-host/Docker collection, no secret echo, config drift, SQL READ ONLY adapter and real PostgreSQL probes passed |
| Final network-options redaction / host boundary isolation | **13 passed**, 2.12 s, after final redaction/isolation changes; prior runtime/SQL suites unaffected |
| Full local Docker image build/start/namespace collector | **Not run:** local Docker Desktop engine pipe absent |
| Full production barrier rehearsal / Telegram replay | **Not run:** actual production runtime/topology unknown; remains a release gate |

The two test runs overlap: their counts are not a count of unique tests. An earlier
integration pass had 74 passed / 3 skipped because Redis was absent; a subsequent
81-test pass included those tests with local Redis and had no skips. An early
manifest regression found Git archive respecting Windows autocrlf; explicit
`core.autocrlf=false`, `core.eol=lf` fixed it, with a portable independent Git fixture.
Existing Pydantic, Alembic and UTC datetime deprecation warnings remain.

Exact final commands (only disposable connection values were injected in the test
process environment; no production `.env` was loaded):

```text
python -m pytest -q -ra --basetemp=.local-test/rollout/integration-final
  --junitxml=.local-test/rollout/integration-final.xml
  tests/test_production_rollout_postgresql.py
  tests/test_worker_drain_postgresql.py
  tests/test_worker_drain_lifecycle_postgresql.py
  tests/test_production_worker_postgresql.py
  tests/test_marketing_mvp_postgresql.py
  tests/test_graph_postgresql.py
  tests/test_workflow_redis.py

python -m pytest -q --basetemp=.local-test/rollout/review-final
  --junitxml=.local-test/rollout/review-final.xml
  tests/test_production_rollout_readonly.py
  tests/test_production_rollout_postgresql.py
  tests/test_worker_control.py
  tests/test_provider_request_telemetry.py
  tests/test_production_graph_worker.py
```

The integration run executes pause-vs-claim concurrency, pending/deferred recovery,
superseded provider fake calls, DB outage/missing control, epoch checks, migration
roundtrip, restricted worker/operator role tests, and persisted pause after the
installed SIGTERM callback. Actual OS/container shutdown is established by CI,
not claimed from the local callback tests.

Collector probes were tested both as real Python subprocesses with a strict
read-only SQL adapter and against actual PostgreSQL. The host/Docker inventory
orchestration test supplies controlled metadata and command responses. It proves
redaction/NO_GO contracts; it does **not** prove actual Linux namespace observation,
Docker image identity, root file permissions, proxy policy or production grants.
The full collector refuses to run on this local host and has no bypass flag.

## Exact merge CI evidence

Read-only GitHub status query on 15 October verified
[run 38650353546](https://github.com/Pickle-Pee/smm_ai_helper/actions/runs/38650353546),
head `c23dfb2cfc3cfab7cd34fe6226b67404d7d0c166`, conclusion success:

- [python job](https://github.com/Pickle-Pee/smm_ai_helper/actions/runs/38650353546/job/116147315787): migrations, schema check and full pytest steps succeeded.
- [container-smoke job](https://github.com/Pickle-Pee/smm_ai_helper/actions/runs/38650353546/job/116147315299): image build, disposable real DB/Redis suite, persistence recreation, both worker lanes/live drain/restart, and fake-provider SIGTERM recovery steps succeeded.

Failure-only diagnostics step was skipped as expected. No raw CI logs were needed.
These statuses apply to the merge SHA, not an as-yet unbuilt production candidate
image or this preparation branch's future CI.

## Review boundary and integrity

Preparation diff was reviewed for read-only behavior, secret exposure, bypass
paths, shallow CI checkout portability, SQL/schema compatibility, bootstrap/rollback
ordering and distinction between code/local/production evidence. Material local
findings (CRLF-dependent hashing, shallow-history test dependency, global empty-DB
test assumption, arbitrary IPAM driver options in output, real cron reads in the
controlled host test) were corrected. Independent operator/release review is still
required; this is not an assertion that the proposed production barrier passed.

Source manifest SHA256 (UTF-8/LF file):
`13623f5e33013f9bb515c1f049fc0099b44f16b4d61dd60138bab1fa333ee98d`.

Collector SHA256 (reviewed local file bytes; verify LF Git-export bytes when
packaging on another platform):
`5a085c4f26317d3c80402fdc2e3202f7098e998cb06a4d7ecca1d3ca3760b168`.

These identify preparation artifacts, not release image IDs. Candidate digest,
rollback image identities, actual production topology/schema/grants and a proven
external bootstrap barrier are **unavailable**. The
[operator runbook](first-production-rollout.md) therefore ends in **NO-GO**.
