"""Offline paired payload capture. No live execution option and no DB access.

Use a local diagnostic snapshot to replay an incident, or the deterministic
synthetic fixture for a shareable report. Only hashes/counts leave memory.
"""
import argparse
import asyncio
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
from unittest.mock import patch

import httpx

from tools.positioning_diagnostics import capture_request, measurement, restore_snapshot, SNAPSHOT_LIMIT
from tools.positioning_schema_diagnostics import schema_metadata
from app.module_execution.executors.provider_schema import nodes


def synthetic_request(*, job=True, alternative=True):
    from app.marketing_orchestrator import AuthorizedContextFact, ContextPacket, PlanningInputKey
    from app.module_execution import ModuleExecutionRequest
    from app.module_registry import ModuleId, ModuleRegistry
    keys = ["product", "target_or_target_hypothesis", "product_truth"]
    keys += ["customer_job_or_need"] if job else []
    keys += ["relevant_alternative"] if alternative else []
    facts = tuple(AuthorizedContextFact(
        "fact." + key, key, "Synthetic supplied " + key,
        input_key=next((item for item in PlanningInputKey if item.value == key), None),
        confidence=0.8, source="synthetic fixture") for key in keys)
    return ModuleExecutionRequest(execution_id="137" + "0" * 29,
        module_id=ModuleId.POSITIONING, objective="Prepare evidence-based marketing output",
        expected_outputs=ModuleRegistry.load("1.3.0").get(ModuleId.POSITIONING).outputs,
        context_packet=ContextPacket(known_facts=facts))


async def compare(request, *, model):
    from app.llm.openai_text import log
    # Interception deliberately aborts the POST; do not report it as a real
    # transport failure or an unknown billing outcome in diagnostic stderr.
    with patch.object(log, "disabled", True):
        baseline = (await capture_request(request, model=model)).payload
        minimal = (await capture_request(request, model=model, minimal_provider_schema=True)).payload
    # Prove equality outside the schema, including instructions and all data.
    left, right = json.loads(json.dumps(baseline)), json.loads(json.dumps(minimal))
    left["text"]["format"].pop("schema")
    right["text"]["format"].pop("schema")
    if left != right:
        raise ValueError("non_schema_payload_difference")
    result = {"schema_version": "positioning_schema_experiment.v1", "live_calls": 0,
        "package_versions": {name: version(name) for name in ("httpx", "pydantic", "jsonschema")},
        "hypothesis": "unproven", "only_changed_path": "text.format.schema",
        "model": baseline["model"], "reasoning": baseline["reasoning"],
        "max_output_tokens": baseline["max_output_tokens"],
        "shared_payload_without_schema": measurement(left),
        "canonicalization": "UTF-8, sorted keys, compact separators, ensure_ascii=False",
        "http_body_encoding": "httpx.Request(json=payload).content; insertion order; no headers"}
    for name, payload in (("original", baseline), ("minimal", minimal)):
        schema = payload["text"]["format"]["schema"]
        body = httpx.Request("POST", "https://offline.invalid/responses", json=payload).content
        result[name] = {"payload": measurement(payload), "schema": measurement(schema),
            "http_body": {"bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()},
            "structure": schema_metadata(schema),
            "required_field_occurrences": sum(len(n.get("required", [])) for n in nodes(schema))}
    return result


async def run(args):
    from app.config import settings
    model = args.model or settings.DEFAULT_TEXT_MODEL_HARD
    if args.snapshot:
        path = Path(args.snapshot)
        if path.stat().st_size > SNAPSHOT_LIMIT or not args.run_id or not args.job_id:
            raise ValueError("invalid_snapshot_arguments")
        request = await restore_snapshot(json.loads(path.read_text(encoding="utf-8")),
            run_id=args.run_id, job_id=args.job_id)
        return {"source": "local_snapshot", "comparison": await compare(request, model=model)}
    return {"source": "synthetic_fixture", "comparisons": {
        f"job_{int(job)}_alternative_{int(alternative)}": await compare(
            synthetic_request(job=job, alternative=alternative), model=model)
        for job, alternative in ((True, True), (False, True), (True, False), (False, False))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot")
    parser.add_argument("--run-id")
    parser.add_argument("--job-id")
    parser.add_argument("--model", help="Capture only; defaults to configured production model")
    args = parser.parse_args()
    if not args.snapshot and (args.run_id or args.job_id):
        parser.error("--run-id and --job-id require --snapshot")
    try:
        report = asyncio.run(run(args))
    except Exception:
        # Snapshot/parser errors may contain business values; never print them.
        parser.exit(1, "offline_schema_experiment_failed\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
