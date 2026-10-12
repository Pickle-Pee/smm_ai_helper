# Verify one real POSITIONING invocation after approval

This procedure is prepared, not executed. It requires separate explicit permission
for one real provider call and for any deployment/environment change. The default
production switch remains false. Do not use diagnostic `--live` completion alone
as release acceptance.

## Preconditions and isolation

Use the approved PR revision in an isolated operator process with secure existing
configuration, read-only PostgreSQL access, `gpt-5-mini` and the unchanged 16000
POSITIONING profile. After authorization only, enable
`POSITIONING_SCHEMA_PROJECTION_ENABLED=true` for this process. Do not start a
queue worker, call claim/load_work, replay a graph automatically or reset a failed
job. This verifies the real production executor/provider/server/Quality Gate path
as one read-only replay; it does not mark the historical failed job successful.

Select the approved run/job using the existing `restore_database` reader. It
validates persisted plan/job/artifact identities, accepted ancestor closure and
dependency barriers without claims or writes, including terminal failed runs.
Its transaction closes before any provider I/O. If the input/schema fingerprints,
seed variant, 13-ID/zero-parent support, or budget differ from the approved A/B
case, stop and review the mismatch before spending a call.

Disable third-party logging in the verification process. Save only the safe
summary to a protected operator evidence file outside Git. Never print the request,
schema, exception traceback, model text, normalized claims, business facts or keys.
No response text or raw snapshot belongs in a PR or issue.

## One-call execution recipe

The following recipe intentionally defaults to unapproved. Fill the approved
identities and set APPROVED=true only after the separate permission. It is not
an automation or a production entrypoint. It performs at most one HTTP request,
has no worker retry/fallback, and does not persist any result.

```python
import asyncio
import json
import logging
import re
from unittest.mock import patch

import httpx
from app.config import settings
from app.llm.openai_text import _response_metadata
from app.model_generation_policy import module_output_tokens
from app.module_execution.acceptance import fully_accepted
from app.module_execution.executors import PositioningExecutor
from app.module_execution.executors.provider_schema import collapse_single_support_anyof, schema_measurement
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.service import evaluate_result
from tools.positioning_diagnostics import capture_request, restore_database, measurement

APPROVED = False
APPROVED_HASHES = {"instructions": "<approved_sha256>", "input": "<approved_sha256>",
                   "schema": "<approved_sha256>"}
RUN_ID = "<approved_run_id>"
JOB_ID = "<approved_job_id>"
logging.disable(logging.CRITICAL)

async def verify():
    if not APPROVED or not settings.POSITIONING_SCHEMA_PROJECTION_ENABLED:
        raise RuntimeError("verification_not_approved_or_enabled")
    if settings.DEFAULT_TEXT_MODEL_HARD != "gpt-5-mini":
        raise RuntimeError("verification_model_mismatch")
    request = await restore_database(run_id=RUN_ID, job_id=JOB_ID)
    baseline = await capture_request(request, model=settings.DEFAULT_TEXT_MODEL_HARD)
    original = baseline.arguments["response_schema"]
    projected = collapse_single_support_anyof(original)
    data = json.loads(baseline.arguments["text"])
    if (len(data["local_evidence"]) != 13 or data["allowed_parent_claim_ids"]
            or len(request.expected_outputs) != 16
            or module_output_tokens(baseline.arguments["output_budget"]) != 16000
            or schema_measurement(original)["bytes"] != 8048
            or schema_measurement(projected)["bytes"] != 4925):
        raise RuntimeError("verification_fingerprint_profile_mismatch")
    restored_hashes = {"instructions": measurement(baseline.arguments["instruction"])["sha256"],
        "input": measurement(baseline.arguments["text"])["sha256"],
        "schema": schema_measurement(original)["sha256"]}
    if restored_hashes != APPROVED_HASHES:
        raise RuntimeError("verification_approved_hash_mismatch")
    summary = {"run_id": RUN_ID, "job_id": JOB_ID,
        "validation_schema": schema_measurement(original),
        "provider_schema": schema_measurement(projected)}
    posts = 0
    async def guard(wire_request):
        nonlocal posts
        if posts >= 1:
            raise RuntimeError("verification_http_call_limit")
        body = json.loads(wire_request.content)
        expected = dict(baseline.payload)
        expected["text"] = {"format": {**baseline.payload["text"]["format"], "schema": projected}}
        if measurement(body)["sha256"] != measurement(expected)["sha256"]:
            raise RuntimeError("verification_wire_mismatch")
        posts += 1
    async def observe(response):
        await response.aread()
        envelope = response.json()
        summary.update(_response_metadata(envelope, 16000))
        summary["http_status"] = response.status_code
        correlation = response.headers.get("x-request-id", "")
        if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", correlation):
            summary["request_id"] = correlation
    original_client = httpx.AsyncClient
    def client(**kwargs):
        return original_client(**kwargs, event_hooks={"request": [guard], "response": [observe]})
    with patch.object(httpx, "AsyncClient", client):
        result = await PositioningExecutor(model_call=production_model_call,
            provider_schema_projection=settings.POSITIONING_SCHEMA_PROJECTION_ENABLED).execute(request)
    summary["http_calls"] = posts
    summary["original_validation"] = "passed"  # execute returned through the unchanged full pipeline.
    summary["normalized_status"] = result.normalized_result.module_status.value
    summary["output_count"] = len(result.normalized_result.claims)
    quality = evaluate_result(request.execution_id, result, request.upstream_results)
    summary["quality_gate_accepted"] = fully_accepted(result,
        quality["accepted_result_ids"], quality["accepted_claim_ids"])
    summary["accepted"] = (posts == 1 and summary.get("http_status") == 200
        and summary.get("response_status") == "completed" and summary["output_count"] == 16
        and summary["normalized_status"] in ("PASS", "PASS_WITH_LIMITATIONS")
        and summary["quality_gate_accepted"])
    return summary

try:
    print(json.dumps(asyncio.run(verify()), sort_keys=True))
except Exception:
    # Fail closed. Operator may record bounded server failure stage/reason using
    # the existing safe diagnostics, but must never print the exception text.
    print('{"accepted":false,"failure":"verification_failed"}')
```

Before the permission-controlled execution, verify the approved original
instruction/input/schema hashes against the restored metadata. The recipe's
APPROVED_HASHES gate enforces this before HTTP; byte counts alone do not establish
request identity. Select a deployment-compatible dependency environment. An
unexpected profile is a stop condition, not permission to change model/budget.

## Acceptance, failure and rollback

Accept only if exactly one request had HTTP 200/completed, the emitted wire matched
the original request with exactly the equivalent schema substitution, and
`PositioningExecutor.execute` returned through original Draft validation,
Pydantic, coverage, support/provenance and semantic checks. Require all 16 claims
and the result to be accepted by the real Quality Gate evaluator/fully_accepted.
PASS_WITH_LIMITATIONS is acceptable only with those complete gates; do not treat
an upstream-only or partial accepted manifest as success.

If execution/schema/semantic validation or a gate fails, record only the bounded
failure stage/reason through safe tooling. Do not repair the model output, drop
validation, increase limits or retry automatically. The failed historical run and
JobExecution remain untouched. Investigate the failure before authorizing more
calls or rollout.

After verification, return the isolated process configuration to false/exit the
process. Wider production enablement requires its own approval. For rollout
rollback, set the flag false and recreate configured API/worker registries;
verify matching schema hashes, applied=false and zero transformed nodes. No DB
state/lease/artifact edits or migrations are part of verification or rollback.
