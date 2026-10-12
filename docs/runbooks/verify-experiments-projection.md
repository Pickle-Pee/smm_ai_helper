# One separately authorized EXPERIMENTS production executor replay

Prepared only; no live call or deployment is authorized by implementation of this
candidate. Obtain explicit permission for one provider call against the approved
revision, restored request fingerprints and run/job. Any server deployment needs
separate permission. Leave the global flag false. One `completed` response never
justifies global rollout.

Incident run: `4cc38ca6ed8c64b0039982fc8a83ff93bd3e165f89390052daa6cc3a718d785e`.
Incident job: `c264b79d868e90f97a00c37d05ac43e6`.
Latest reported replay: `req_06d7388ca87640c180cd187eb4b0bd27` completed with
2437 output tokens but failed during result construction. The recipe now returns
`failure_rule` and available zero-based `output_index` / `experiment_index` on
such rejection, without response text or exception details. See the
[closed rule definitions and unchanged kind mismatch](../development/experiments-result-diagnostics.md).
All four fingerprints below are pinned to the latest production incident for
this run/job. Explicit permission for one live call is still required; the
reported fingerprints do not grant approval.

Use an isolated operator process with the approved code/dependencies, existing
secure credentials and read-only PostgreSQL privileges. Do not start workers,
claim/reset jobs, dispatch a persisted graph, enqueue or write artifacts. Shared
read-only restoration validates the persisted plan and accepted ancestor closure;
the transaction closes before model I/O. A replay does not alter historical status.

Before authorization, restore/capture offline and privately review hashes for
instruction, input and original schema. Current persisted state/builders may
differ from the incident: stop on mismatch. Keep the incident fingerprints below;
do not replace them with current captures to bypass a mismatch.
Confirm all 16 requested canonical names, strategic parents, incident model and
16000 budget. Schema byte counts alone do not establish request identity.

After permission, enable `EXPERIMENTS_SCHEMA_PROJECTION_ENABLED=true` only in the
operator process. Leave the POSITIONING flag untouched. Disable all third-party
logging; output only safe metadata to protected operator evidence outside Git.
Never print exceptions, snapshots, schemas, requests, responses or evidence IDs.

```python
import asyncio
from copy import deepcopy
import hashlib
import json
import logging
from unittest.mock import patch

import httpx
from jsonschema import Draft202012Validator
from app.config import settings
from app.llm.openai_text import _response_metadata
from app.module_execution.acceptance import fully_accepted
from app.module_execution.executors import ExperimentsExecutor
from app.module_execution.executors.common import ResultContractError
from app.module_execution.executors.experiments import strategic_parents
from app.module_execution.executors.intelligence_schemas import ExperimentsOutput
from app.module_execution.executors.provider_schema import schema_measurement
from app.module_execution.executors.schema_annotations import strip_schema_annotations
from app.module_registry import ModuleId, ModuleRegistry
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.service import evaluate_result
from app.orchestration_runtime.serialization import result_to_json
from tools.experiments_diagnostics import capture_request, restore_database

APPROVED = False
APPROVED_HASHES = {
    "instructions": "b9a6ae79b33e9d781251adbca9c659b279f8ed1965e8076a6b01bce0e02143eb",
    "input": "1bf797958c85b225429735385dae90e26f102c2c17071ea6e96d8cc425947c85",
    "schema": "49c9d21c942a1c5dd97af086fc1189e8d2f78ebd294edc58a1546b0e55560150",
}
APPROVED_PROVIDER_SCHEMA_HASH = "27e6f30e45dd5aa10a5d5ee83a1e4529ec483e863f8d8c497c8cb80022582d68"
RUN_ID = "4cc38ca6ed8c64b0039982fc8a83ff93bd3e165f89390052daa6cc3a718d785e"
JOB_ID = "c264b79d868e90f97a00c37d05ac43e6"
logging.disable(logging.CRITICAL)

async def verify():
    if not APPROVED or not settings.EXPERIMENTS_SCHEMA_PROJECTION_ENABLED:
        raise RuntimeError("verification_not_approved_or_enabled")
    if settings.DEFAULT_TEXT_MODEL_HARD != "gpt-5-mini":
        raise RuntimeError("verification_model_mismatch")
    request = await restore_database(run_id=RUN_ID, job_id=JOB_ID)
    baseline = await capture_request(request)  # Explicitly unprojected, no provider call.
    original = baseline.arguments["response_schema"]
    projected, removed = strip_schema_annotations(original)
    names = set(ModuleRegistry.load("1.3.0").get(ModuleId.EXPERIMENTS).outputs)
    if (set(request.expected_outputs) != names or len(request.expected_outputs) != 16
            or not strategic_parents(request) or not removed
            or baseline.payload["max_output_tokens"] != 16000):
        raise RuntimeError("verification_profile_mismatch")
    hashes = {"instructions": hashlib.sha256(baseline.arguments["instruction"].encode("utf-8")).hexdigest(),
              "input": hashlib.sha256(baseline.arguments["text"].encode("utf-8")).hexdigest(),
              "schema": schema_measurement(original)["sha256"]}
    if (schema_measurement(projected)["sha256"] !=
            APPROVED_PROVIDER_SCHEMA_HASH):
        raise RuntimeError("verification_provider_fingerprint_mismatch")
    if hashes != APPROVED_HASHES:
        raise RuntimeError("verification_fingerprint_mismatch")
    expected = deepcopy(baseline.payload)
    expected["text"]["format"]["schema"] = projected
    summary = {"validation_schema": schema_measurement(original),
               "provider_schema": schema_measurement(projected),
               "removed_annotations": removed}
    posts = 0
    async def guard(wire):
        nonlocal posts
        if posts >= 1 or wire.method != "POST" or json.loads(wire.content) != expected:
            raise RuntimeError("verification_wire_or_call_limit")
        posts += 1
    async def observe(response):
        await response.aread()
        envelope = response.json()
        summary.update(_response_metadata(envelope, 16000))
        summary["http_status"] = response.status_code
        if response.status_code != 200 or summary["response_status"] != "completed":
            raise RuntimeError("verification_not_completed")
    original_client = httpx.AsyncClient
    def client(**kwargs):
        return original_client(**kwargs, event_hooks={"request": [guard], "response": [observe]})
    try:
        with patch.object(httpx, "AsyncClient", client):
            result = await ExperimentsExecutor(model_call=production_model_call,
                provider_schema_projection=settings.EXPERIMENTS_SCHEMA_PROJECTION_ENABLED).execute(request)
    except ResultContractError as exc:
        summary.update(accepted=False, http_calls=posts, failure=exc.stage.value,
                       failure_rule=exc.failure_rule.value)
        if exc.output_index is not None:
            summary["output_index"] = exc.output_index
        if exc.experiment_index is not None:
            summary["experiment_index"] = exc.experiment_index
        return summary
    # execute has already validated raw response with original schema + Pydantic,
    # provenance, every-output strategic citation, numeric grounding and exact
    # constraints for every design. Recheck the returned payload independently.
    payload = result_to_json(result)["payload"]
    Draft202012Validator(original).validate(payload)
    ExperimentsOutput.model_validate(payload)
    outputs = payload["outputs"]
    designs = payload["experiments"]
    quality = evaluate_result(request.execution_id, result, request.upstream_results)
    accepted = fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])
    summary.update(http_calls=posts, original_schema_valid=True, pydantic_valid=True,
        semantic_provenance_grounding_constraints_valid=True,
        output_count=len(outputs), experiment_design_count=len(designs),
        normalized_status=result.normalized_result.module_status.value,
        quality_gate_accepted=accepted)
    summary["accepted"] = (posts == 1 and len(outputs) == len(result.normalized_result.claims) == 16
        and {o["output_name"] for o in outputs} == names and 1 <= len(designs) <= 3
        and result.normalized_result.module_status.value in ("PASS", "PASS_WITH_LIMITATIONS") and accepted)
    return summary

try:
    print(json.dumps(asyncio.run(verify()), sort_keys=True))
except Exception:
    print('{"accepted":false,"failure":"verification_failed"}')
```

Accept only HTTP 200/`completed`, exact approved wire (only annotation removal),
original JSON Schema + Pydantic, all 16 distinct canonical outputs, valid
ExperimentDesign(s), eligible strategic citations in every output, numerical
grounding, exact time/resource constraints, provenance and full Quality Gate
acceptance of this result and every claim. Missing/partial accepted manifests
fail. PASS_WITH_LIMITATIONS requires the same complete acceptance.

On failure stop: no automatic retries, output repair, model/budget adjustment,
weaker validation or job edits. Record bounded stages/reasons only. A further
replay or rollout requires separate approval and review of the failure evidence.

Rollback: exit the isolated process and restore its flag to false. For any later
authorized rollout, set `EXPERIMENTS_SCHEMA_PROJECTION_ENABLED=false` and recreate
the configured API/worker registries. Verify enabled=false, applied=false, zero
removed annotations and equal original/provider hashes and sizes. POSITIONING
remains independently configured. No database/lease/artifact change or migration
is needed. Wider rollout requires its own evidence and explicit authorization.
