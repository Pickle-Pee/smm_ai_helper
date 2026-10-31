"""Read-only replay using production builders; raw values stay in memory.

Run as a standalone process: HTTP interception temporarily patches the client
factory and settings, so this module must not be used inside a running worker.
"""
import argparse
import asyncio
import copy
from dataclasses import dataclass, field, replace
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import patch

from tools.positioning_schema_diagnostics import SCHEMA_CASES, schema_metadata, schema_variants


CASES = ("baseline", "no_core", "small_context", "simple_schema", "alternate_model", *SCHEMA_CASES)
HARD_CALL_LIMIT = 4
SNAPSHOT_LIMIT = 16 * 1024 * 1024


class DiagnosticError(ValueError):
    """Only closed error text may cross the CLI boundary."""


class _Captured(BaseException):
    pass


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def measurement(value):
    raw = (value if isinstance(value, str) else compact(value)).encode("utf-8")
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


@dataclass(repr=False)
class Replay:
    payload: dict = field(repr=False)
    arguments: dict = field(repr=False)


async def capture_request(request, *, model, minimal_provider_schema=False):
    """Execute POSITIONING up to its provider boundary, then real wire builder."""
    from app.module_execution.executors import PositioningExecutor
    arguments = {}

    async def capture(**kwargs):
        arguments.update(kwargs)
        raise _Captured()

    class DiagnosticExecutor(PositioningExecutor):
        def provider_schema_for(self, request, validation_schema):
            # Explicit offline control: retain the original canonical schema.
            # Production always applies its observation-generation subset.
            if not minimal_provider_schema:
                return copy.deepcopy(validation_schema)
            return super().provider_schema_for(request, validation_schema)

    try:
        await DiagnosticExecutor(model_call=capture, provider_schema_projection=False,
            minimal_provider_schema=minimal_provider_schema).execute(request)
    except _Captured:
        pass
    if not arguments:
        raise DiagnosticError("request_not_executable")
    return Replay(await capture_wire(arguments, model=model), arguments)


async def capture_wire(arguments, *, model):
    from app.config import settings
    from app.orchestration_runtime.model_adapter import production_model_call
    import httpx
    payload = {}

    class CaptureClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, *, headers, json):
            payload.update(copy.deepcopy(json))
            raise _Captured()

    # No real client is constructed, no credentials/URL are copied or emitted.
    with patch.object(httpx, "AsyncClient", CaptureClient), patch.object(settings, "DEFAULT_TEXT_MODEL_HARD", model):
        try:
            await production_model_call(**arguments)
        except _Captured:
            pass
    if not payload:
        raise DiagnosticError("wire_not_captured")
    return payload


def metadata(replay):
    from app.prompts.expert_core import EXPERT_CORE_VERSION, load_expert_core
    from app.services.expert_instruction_composer import (
        SPECIALIZED_MODULE_START, SPECIALIZED_MODULE_END, RESPONSE_MODE_START, RESPONSE_MODE_END,
    )
    payload = replay.payload
    instruction = payload["input"][0]["content"]
    data = json.loads(payload["input"][1]["content"])
    core = load_expert_core()
    components = {
        "instructions": measurement(instruction), "input": measurement(payload["input"][1]["content"]),
        "schema": measurement(payload["text"]["format"]["schema"]),
        "expert_core": measurement(core), "payload": measurement(payload),
    }
    for name, start, end in (("specialized", SPECIALIZED_MODULE_START, SPECIALIZED_MODULE_END),
                             ("response_mode", RESPONSE_MODE_START, RESPONSE_MODE_END)):
        components[name] = measurement(instruction.split(start, 1)[1].split(end, 1)[0].strip())
    for name in ("context", "local_evidence", "upstream_results"):
        components[name] = measurement(data[name])
    sections = list(re.finditer(r"^# (\d+)\. .+$", core, re.MULTILINE))
    return {
        "baseline_mode": "original_unprojected",
        "components": components, "expert_core_version": EXPERT_CORE_VERSION,
        "facts_count": len(data["context"]["known_facts"]),
        "evidence_ids_count": len(data["local_evidence"]),
        "parent_claim_ids_count": len(data["allowed_parent_claim_ids"]),
        "output_fields_count": len(data["expected_outputs"]),
        "core_sections_count": len(sections),
        "core_sections": [dict(index=i + 1, **measurement(core[m.start():sections[i + 1].start()
                          if i + 1 < len(sections) else len(core)])) for i, m in enumerate(sections)],
        "core_copies": instruction.count(core),
        "schema_structure": schema_metadata(payload["text"]["format"]["schema"]),
    }


def _graph():
    from app.module_execution.executors import build_module_executor_registry
    from app.orchestration_runtime.service import GraphExecutionService
    # No capability is ever executed while reading the graph.
    async def forbidden(**kwargs):
        raise DiagnosticError("unexpected_capability")
    return GraphExecutionService(executors=build_module_executor_registry(
        model_call=forbidden, analyzer=None, registry_version="1.3.0"))


async def restore(session, *, run_id, job_id, module_id=None):
    """Reuse SELECT-only production validators; terminal run status is irrelevant."""
    from app.module_execution import ModuleExecutionRequest
    from app.module_registry import ModuleId
    from app.orchestration_runtime.contracts import module_job_id
    module_id = module_id or ModuleId.POSITIONING
    graph = _graph()
    revision, plan = await graph._plan(session, run_id)
    jobs, accepted = await graph._graph_state(session, run_id, revision, plan)
    nodes = [n for n in plan.nodes if module_job_id(run_id, revision, n.node_id) == job_id]
    if len(nodes) != 1 or nodes[0].module_id is not module_id:
        raise DiagnosticError("module_job_not_found")
    node = nodes[0]
    if node.node_id not in jobs or not graph._ready(plan, node, jobs, accepted):
        raise DiagnosticError("dependency_barrier_unsatisfied")
    packet = node.context_packet
    # The target had not failed when its original request was dispatched.
    # In particular EXPERIMENTS is optional: its own later failure must not
    # appear in the reconstructed pre-execution evidence coverage.
    coverage = graph._coverage(plan, {key: value for key, value in jobs.items()
                                      if key != node.node_id}, accepted)
    if coverage is not None:
        packet = replace(packet, open_questions=(*packet.open_questions,
            "Evidence coverage (limitations, not factual claims): " + json.dumps(coverage, sort_keys=True)))
    return ModuleExecutionRequest(execution_id=job_id, module_id=node.module_id,
        objective=node.objective, expected_outputs=node.expected_outputs, context_packet=packet,
        upstream_results=graph._upstream(plan, node, accepted))


async def restore_snapshot(snapshot, *, run_id, job_id, module_id=None):
    """Local table projection: no DB session or connection is opened."""
    from app.module_registry import ModuleId
    from app.models import Job, JobStatus, MarketingArtifact, OrchestrationPlanRecord
    module_id = module_id or ModuleId.POSITIONING
    from app.orchestration_runtime.contracts import WORKFLOW_TYPE
    if (snapshot["schema_version"] != module_id.value.lower() + "_diagnostic_snapshot.v1"
            or snapshot["run"]["run_id"] != run_id
            or snapshot["run"]["workflow_type"] != WORKFLOW_TYPE):
        raise DiagnosticError("snapshot_identity_mismatch")
    row = snapshot["plan_record"]
    if row["run_id"] != run_id or row["status"] != "active":
        raise DiagnosticError("snapshot_plan_mismatch")
    plan = SimpleNamespace(**{k: row[k] for k in (
        "revision", "source_plan_id", "registry_version", "compiled_plan_fingerprint", "compiled_plan_json")})
    jobs = []
    for row in snapshot["jobs"]:
        if row["marketing_run_id"] != run_id:
            raise DiagnosticError("snapshot_job_mismatch")
        jobs.append(SimpleNamespace(**{k: row[k] for k in (
            "job_id", "kind", "workflow_step", "payload_json", "result_json", "error")}, status=JobStatus(row["status"])))
    artifacts = []
    for row in snapshot["artifacts"]:
        if row["run_id"] != run_id:
            raise DiagnosticError("snapshot_artifact_mismatch")
        artifacts.append(SimpleNamespace(**{k: row[k] for k in (
            "artifact_key", "artifact_type", "step", "payload_json")}))
    if len({j.job_id for j in jobs}) != len(jobs) or len({a.artifact_key for a in artifacts}) != len(artifacts):
        raise DiagnosticError("snapshot_duplicate_identity")

    class SnapshotSession:
        async def scalar(self, query):
            if query.column_descriptions[0]["entity"] is not OrchestrationPlanRecord:
                raise DiagnosticError("unexpected_snapshot_query")
            return plan

        async def scalars(self, query):
            entity = query.column_descriptions[0]["entity"]
            rows = jobs if entity is Job else artifacts if entity is MarketingArtifact else None
            if rows is None:
                raise DiagnosticError("unexpected_snapshot_query")
            return SimpleNamespace(all=lambda: rows)

    return await restore(SnapshotSession(), run_id=run_id, job_id=job_id, module_id=module_id)


async def restore_database(*, run_id, job_id, module_id=None):
    from sqlalchemy import select, text
    from app.db import AsyncSessionLocal, engine
    from app.models import MarketingRun
    from app.orchestration_runtime.contracts import WORKFLOW_TYPE
    try:
        async with AsyncSessionLocal() as session, session.begin():
            await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
            run = await session.scalar(select(MarketingRun.run_id).where(
                MarketingRun.run_id == run_id, MarketingRun.workflow_type == WORKFLOW_TYPE))
            if run is None:
                raise DiagnosticError("run_not_found")
            return await restore(session, run_id=run_id, job_id=job_id, **({"module_id": module_id} if module_id else {}))
    finally:
        await engine.dispose()


def variants(replay, *, alternate_model=None):
    """One factor per case; no changes to production or original payload."""
    from app.prompts.expert_core import load_expert_core
    baseline = replay.payload
    result = {name: copy.deepcopy(baseline) for name in CASES
              if name not in SCHEMA_CASES and (name != "alternate_model" or alternate_model)}
    result["no_core"]["input"][0]["content"] = baseline["input"][0]["content"].replace(load_expert_core(), "", 1)
    # Remove business context, but preserve support identities and output slots.
    result["small_context"]["input"][1]["content"] = compact({
        "objective": "Diagnostic synthetic positioning", "expected_outputs": json.loads(baseline["input"][1]["content"])["expected_outputs"],
        "evidence_ids": [e["evidence_id"] for e in json.loads(baseline["input"][1]["content"])["local_evidence"]],
        "parent_claim_ids": json.loads(baseline["input"][1]["content"])["allowed_parent_claim_ids"],
    })
    # Keep the same output shape to avoid a competing instruction to emit a
    # different root object. Remove discriminated branches and support enums.
    statement = {"output_name": {"type": "string"}, "text": {"type": "string"},
                 "kind": {"type": "string"}, "confidence": {"type": "string"},
                 "evidence_ids": {"type": "array", "items": {"type": "string"}},
                 "parent_claim_ids": {"type": "array", "items": {"type": "string"}}}
    properties = {"outputs": {"type": "array", "items": {"type": "object",
        "properties": statement, "required": list(statement), "additionalProperties": False}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}}}
    result["simple_schema"]["text"]["format"]["schema"] = {
        "type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
    if alternate_model:
        result["alternate_model"]["model"] = alternate_model
    result.update(schema_variants(baseline))
    return result


async def live_probe(payloads, *, cases, max_calls, opt_in=False):
    """Explicit, bounded, one POST per case. No parsing/logging of output text."""
    if (not opt_in or type(max_calls) is not int or not 1 <= max_calls <= HARD_CALL_LIMIT
            or not cases or len(cases) > max_calls or len(set(cases)) != len(cases)
            or any(case not in payloads for case in cases)):
        raise DiagnosticError("live_policy_rejected")
    import httpx
    from app.config import settings
    from app.llm.openai_text import _response_metadata
    results = []
    async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT) as client:
        for case in cases:
            record = {"case": case}
            try:
                response = await client.post(settings.OPENAI_BASE_URL.rstrip("/") + "/responses",
                    headers={"Authorization": "Bearer " + settings.OPENAI_API_KEY}, json=payloads[case])
                record["http_status"] = response.status_code
                request_id = response.headers.get("x-request-id", "")
                if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id):
                    record["request_id"] = request_id
                data = response.json()
                record.update(_response_metadata(data, payloads[case]["max_output_tokens"]))
                usage = data.get("usage") if isinstance(data, dict) else None
                details = usage.get("output_tokens_details") if isinstance(usage, dict) else None
                for name, container, cap in (("input_tokens", usage, 2**31 - 1),
                        ("output_tokens", usage, payloads[case]["max_output_tokens"]),
                        ("reasoning_tokens", details, payloads[case]["max_output_tokens"])):
                    value = container.get(name) if isinstance(container, dict) else None
                    if type(value) is int and 0 <= value <= cap:
                        record[name] = value
                reason = (data.get("incomplete_details") or {}).get("reason") if isinstance(data, dict) and isinstance(data.get("incomplete_details"), dict) else None
                record["incomplete_reason"] = reason if reason in ("max_output_tokens", "content_filter") else "other_or_missing"
            except (httpx.HTTPError, ValueError):
                record["failure"] = "transport_or_envelope"
            results.append(record)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description="Safe read-only POSITIONING replay (offline by default)")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path)
    source.add_argument("--database-read", action="store_true")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--model", default="gpt-5-mini", help="Incident model; memory-only diagnostic setting")
    parser.add_argument("--alternate-model")
    parser.add_argument("--schema-only", action="store_true", help="Baseline and single-group schema variants only")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--case", action="append", choices=CASES)
    parser.add_argument("--max-calls", type=int)
    args = parser.parse_args(argv)
    # Suppress third-party transport/config/SQL logging, including debug mode.
    logging.disable(logging.CRITICAL)
    invalid_schema_case = args.schema_only and args.case and any(
        case not in ("baseline", *SCHEMA_CASES) for case in args.case)
    if invalid_schema_case or (not args.live and (args.case or args.max_calls is not None)) or (args.live and (
            not args.case or args.max_calls is None or not 1 <= args.max_calls <= HARD_CALL_LIMIT
            or len(args.case) > args.max_calls or len(set(args.case)) != len(args.case)
            or ("alternate_model" in args.case and not args.alternate_model))):
        print('{"error":"live_policy_rejected"}')
        return 2
    if not args.database_read and not args.live:
        # Allow standalone offline use without secrets, .env or usable DB config.
        os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://offline:offline@localhost/offline")
        os.environ.setdefault("TELEGRAM_BOT_TOKEN", "offline")
        os.environ.setdefault("OPENAI_API_KEY", "offline")

    async def execute():
        if args.snapshot:
            with args.snapshot.open("rb") as stream:
                raw = stream.read(SNAPSHOT_LIMIT + 1)
            if len(raw) > SNAPSHOT_LIMIT:
                raise DiagnosticError("snapshot_too_large")
            request = await restore_snapshot(json.loads(raw), run_id=args.run_id, job_id=args.job_id)
        else:
            request = await restore_database(run_id=args.run_id, job_id=args.job_id)
        replay = await capture_request(request, model=args.model)
        payloads = variants(replay, alternate_model=args.alternate_model)
        if args.schema_only:
            payloads = {case: value for case, value in payloads.items() if case in ("baseline", *SCHEMA_CASES)}
        report = metadata(replay)
        report["schema_matrix"] = {case: {"schema": measurement(value["text"]["format"]["schema"]),
            "structure": schema_metadata(value["text"]["format"]["schema"]),
            "changed": value["text"]["format"]["schema"] != replay.payload["text"]["format"]["schema"]}
            for case, value in payloads.items() if case in ("baseline", *SCHEMA_CASES)}
        report["matrix"] = {case: measurement(value) for case, value in payloads.items()}
        if args.live:
            report["probes"] = await live_probe(payloads, cases=args.case, max_calls=args.max_calls, opt_in=True)
        print(compact(report))

    try:
        asyncio.run(execute())
    except Exception:
        # Exceptions from codecs/SQL/providers may contain sensitive input.
        print('{"error":"diagnostic_failed"}')
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
