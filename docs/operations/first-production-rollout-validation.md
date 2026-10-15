# Local preparation evidence — 15 October 2026

Scope: first rollout #122/#123, source target
`c23dfb2cfc3cfab7cd34fe6226b67404d7d0c166`. Production access, server build/deploy,
production migration, real Telegram polling and paid provider requests: **not run**.
No app/bot runtime, models, budgets, provider configuration or merged migrations
changed by this preparation.

## Current executed results

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
| Final network-options redaction / collector regression | **13 passed**, 2.13 s, after the final redaction-only change; prior runtime/SQL suites unaffected |
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
test assumption, arbitrary IPAM driver options in output) were corrected. Independent operator/release review is still
required; this is not an assertion that the proposed production barrier passed.

Source manifest SHA256 (UTF-8/LF file):
`02e59ba800a409d4b4edcbc893acb857bc475a70f5b579146ceb4786822db530`.

Collector SHA256 (reviewed local file bytes; verify LF Git-export bytes when
packaging on another platform):
`7cc31552cc0cb7adb23200f647853b7c8068a5058c2f4c553fbba8d07a92118d`.

These identify preparation artifacts, not release image IDs. Candidate digest,
rollback image identities, actual production topology/schema/grants and a proven
external bootstrap barrier are **unavailable**. The
[operator runbook](first-production-rollout.md) therefore ends in **NO-GO**.
