# POSITIONING provider projection: gated production change

Date: 2026-10-12. Base: `master` at `093f404`, after PR #113.

## Evidence and scope

Operator-confirmed A/B with unchanged instructions/context/model `gpt-5-mini` and
16000 budget:

- Baseline: HTTP 200, incomplete/max_output_tokens, zero usage, empty output,
  request `req_b4c18011ef864e56a3e94e81d4175e9d`.
- Equivalent collapse: HTTP 200, completed, input=16357/output=3573/reasoning=640,
  request `req_fd0ec4db5d56468f9dc199c11ad540d1`.
- Schema 8048 → 4925 bytes, anyOf 5 → 1, same 13 local IDs and zero parents,
  mandatory evidence minItems=1 retained.

This supports a narrowly gated provider representation change. It does not by
itself establish full server/Quality Gate acceptance of that live response.
No live requests or deployment were performed while implementing this PR.

## Authoritative contracts and path

Persisted plan → ModuleExecutionRequest → PositioningExecutor → BaseExecutor.generate
remains the current authoritative execution path. `support_response_schema` and
the seed-selected Pydantic output type still produce the full original contract.
`generate` now names that `validation_schema`, constructs its Draft202012Validator,
and independently obtains a `provider_schema` before composition/model call.
Only `provider_schema` crosses the model capability boundary.

The provider copy cannot mutate the original validator's schema, including through
an injected capability. JSON parsing, non-finite-value rejection, Pydantic,
coverage, identity/reference validation, provenance, seed/differentiation/product
truth semantics and outer Quality Gates remain in their original order. No model,
Core, output budget, retry policy, schema version, binding, DTO, artifact format or
persisted plan field changes. No migrations are needed.

One production implementation lives in
`app/module_execution/executors/provider_schema.py`. It is the PR #113 algorithm,
including its narrow proof/refusal conditions. Shared schema-position traversal
also moves there; diagnostic tools import that implementation, not vice versa.
There is no duplicated collapse algorithm or production import from tools.

Only POSITIONING overrides the provider-schema hook. Enabled projection runs only
when single support targets exist. Two-branch support ORs remain unchanged;
no-target cases are independent copies with identical hashes. All other executors
receive copies with exactly the same model arguments/wire content as before.

Proof failure raises `SchemaProjectionError`, a closed ModuleExecutionContractError,
before any model call. It is non-retryable under the unchanged worker classifier.
There is no baseline/loose-schema fallback; no partial candidate is returned.

## Switch and rollout/rollback

`POSITIONING_SCHEMA_PROJECTION_ENABLED` is a boolean server setting, default **false**.
`.env.example` also keeps it false. Production graph composition injects the flag
into only the POSITIONING executor. The API and graph worker use that common
composition; direct copilot execution and durable graphs share the configured
registry. Runtime-neutral/manual executor construction also defaults to disabled
and accepts an explicit boolean policy for tests/controlled verification.

The PR alone does not enable or deploy the change. After separate approval for
validation/deployment, set the flag true in the designated API/worker environment
and recreate those processes/registries using the approved revision. Confirm the
actual model/budget remain the approved existing values. Configuration is read
at composition time; changing an environment value does not update old executors.

Rollback: set the flag false and recreate the affected processes/registries.
Verify enabled=false/applied=false, node count zero and equal original/provider
hashes. No DB edits, lease resets, new contract versions or data migrations are
required. Already dispatched requests cannot be unsent; both schemas enforce
the same result language, and original server validation always remains active.

## Safe diagnostics and baseline parity

POSITIONING emits one INFO event with module/execution identity, enabled/applied
booleans, transformed-node count, original/provider UTF-8 byte counts and canonical
SHA-256 hashes. Hashes use sorted-key compact JSON, not HTTP framing. Metrics
contain no schema contents, prompts, evidence IDs, business data or credentials.
Disabled and parent-supported no-op cases emit matching hashes and zero nodes.
Proof refusal emits only execution identity and the closed equivalence_unproved
code. Existing safe output-failure stages remain unchanged.

`tools.positioning_diagnostics.capture_request` explicitly constructs a disabled
POSITIONING executor. Its baseline is always the original unprojected request,
even in an environment where the production flag is true. Metadata labels this
`baseline_mode=original_unprojected`. The named equivalent-collapse case remains
an explicitly projected diagnostic candidate. Default baseline parity compares
with disabled production; enabled parity compares only after the named projection.
The original instruction/input/model/reasoning/output budget never silently change.

The CLI remains offline by default. Its PostgreSQL reader remains REPEATABLE READ
READ ONLY and never claims JobExecution. Live diagnostic probes still require
explicit opt-in, selected cases and the four-call cap. Those envelope-only probes
are not sufficient evidence for release acceptance; use the separate procedure.

## Verification and remaining gate

The existing PR #113 equivalence tests now import the production implementation
and cover all four seed types, 13-ID local allowlists, parents/no-parents and
adversarial objects. New tests compare real HTTPX MockTransport requests against
the original diagnostic baseline plus exactly the approved projection, while
tracking the unchanged server validator and evaluating actual Quality Gates.
They exercise safe INFO logging, configuration injection, disabled behavior,
parent-supported no-op, proof refusal without a call/retry, provider-copy mutation,
unknown IDs, empty support, wrong kinds/names, coverage, duplicate IDs, truth
support semantics, string bounds and non-finite numeric JSON. Existing numerical
support rules in other modules remain covered by their original suites.

Five non-POSITIONING modules are explicitly compared with the flag off/on; all
model arguments remain identical. Diagnostic CLI subprocesses run with the
production flag true but real HTTP clients and DB sessions blocked, and still
report the original baseline. Full exact-HEAD CI/container-smoke results are
recorded in the PR. Final diff review must confirm no unrelated contract changes.

Keep the rollout gate disabled until the separately authorized one-call procedure
demonstrates response completion **and** original server validation **and** full
Quality Gate acceptance. The procedure is in
[verify-positioning-projection.md](../runbooks/verify-positioning-projection.md).
