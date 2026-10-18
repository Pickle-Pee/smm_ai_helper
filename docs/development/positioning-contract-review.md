# POSITIONING A/B review package — 2026-10-18

Source baseline and fetched origin/master:
`0441c49e3938c962f5165adae4f96916df164e1a`.
Working branch: `codex/positioning-contract`, isolated under `.worktrees/positioning-contract`.
The original checkout and unrelated local edits are preserved.

## Independent diffs

* A: commit `3c333bd`, diagnostic-only. No wire/acceptance/retry/persistence changes.
* B: commit carrying this report, product-support wire v2. Constructor opt-in only;
  production factories retain default v1. B's patch applies directly to the source
  baseline, verified with a separate Git index and a separate baseline+B checkout.
  It does not depend on A's telemetry implementation.

The exported A/B patch files are outside the commits in the task's local review
package. The complete diffs include code, tests and documentation. No push or PR.

## Executed test reports

| Run | Result |
| --- | --- |
| Stage A: metadata + existing output/seed/support/executor/diagnostics/projection/equivalence suites | 659 PASS, 4 warnings, 43.54s |
| Final focused: production-rollout readonly tests + B suite + A metadata | 535 PASS, 4 warnings, 72.44s |
| A strengthened output-permutation regression, actual model order differs from request order | 25 PASS, 1.06s |
| B alone on baseline, with A absent | 481 PASS, 4 warnings, 68.30s |
| Full offline regression after fixture correction | 3865 PASS, 216 SKIP, 30 warnings, 208.94s |

The B suite contains the full 448/448 matrix (four names × four kinds × four seed
states × seven modes), plus explicit mapping, versioning, bounds, all-output
compatibility, serialization, original validation defenses, MockTransport adapter,
Quality Gates and fingerprint tests. Stage A's 25 new cases exercise actual
indices 0–3, output permutation, known/unknown closed categories, safe correlation
and private sentinel exclusion. Existing replay and privacy tests were retained.

Commands (using the root `.venv/Scripts/python.exe`, from the isolated worktree):

```powershell
python -m pytest -q tests/test_positioning_statement_metadata.py tests/test_positioning_diagnostics.py tests/test_positioning_output.py tests/test_positioning_seed_contract.py tests/test_statement_support_contract.py tests/test_support_identity_schema.py tests/test_module_executors.py tests/test_positioning_schema_diagnostics.py tests/test_positioning_provider_projection.py tests/test_positioning_equivalent_schema.py --basetemp=.pytest-stage-a --disable-warnings --tb=short
python -m pytest -q tests/test_production_rollout_readonly.py tests/test_positioning_product_wire.py tests/test_positioning_statement_metadata.py --basetemp=.pytest-contract-final --disable-warnings --tb=short
python -m pytest -q tests/test_positioning_statement_metadata.py --disable-warnings --tb=short
python -m pytest -q tests/test_positioning_product_wire.py --disable-warnings --tb=short
$env:MVP_TEST_DATABASE_URL=''; $env:DURABLE_JOB_TEST_DATABASE_URL=''; $env:REDIS_TEST_URL=''
python -m pytest -q --basetemp=.pytest-regression-verified --disable-warnings --tb=short
python -m tests.positioning_product_wire_report
```

The B-alone command ran in a temporary index export of baseline plus exactly the
B candidate patch, with no A source files or changes. The patch was first checked
with `git apply --cached --check` against a baseline index. Only later report text
differs from that tested candidate; runtime code and tests are the same.

Initial runs caught synthetic-fixture mistakes (fact-ID grammar, immutable JSON
conversion, canonical lineage ordering and Quality Gate job-ID grammar), fixed
before passing runs. Sandbox Windows asyncio socketpair initialization blocked;
offline suites used approved execution outside that sandbox and workspace temp.

The first full run had 3864 PASS / 216 SKIP / 1 FAIL. Its only failure was an
existing manifest generator test comparing current copied sources with historical
release hashes. The test now compares its own temporary Git fixture's exact
committed bytes. Historical production manifest, digest and authentication tests
are unchanged. This test-only correction is necessary for regression on changed
runtime files; it does not update or authorize the historical release package.

## Review and limitations

Independent static review of A and B: no unresolved material findings. Two findings
were resolved: preserve the original diagnostics test file when adding new tests;
distinguish original validation, v2 wire and provider fingerprint labels. The
manifest test correction also received an independent scope/correctness review.
Final source diff passed `git diff --check`.

This package stops for the user's independent review. No remote CI ran. Skipped
PostgreSQL/Redis tests are not claimed as passed; production SQL was prohibited.
Synthetic accepted artifacts roundtrip through actual serializers; actual
historical artifacts were neither read nor rewritten. The original production
response remains unavailable. No historical failed jobs or evidence changed.

No real OpenAI POST, automatic recovery/retry, production SQL, SSH, deploy, push, PR or merge
was performed. Local in-memory SQLite queries in tests were allowed. HTTP serialization tests used MockTransport. Provider compatibility
is established against the documented standard-model schema subset and bounded
offline schemas; live provider acceptance is unverified and remains a separately
authorized rollout gate. There is no automatic activation in this change.

See [A behavior and rollback](positioning-stage-a.md),
[B contract compatibility / rollout / rollback](positioning-product-wire-v2.md),
and [schema measurements](positioning-product-wire-measurements.json).
