"""Standalone read-only VIRTUAL_CMO replay; never import into a worker process."""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import re
from unittest.mock import patch

from tools.positioning_diagnostics import (
    DiagnosticError, Replay, SNAPSHOT_LIMIT, _Captured, capture_wire, compact,
    measurement, metadata, restore_database as shared_database,
    restore_snapshot as shared_snapshot,
)


async def restore_snapshot(snapshot, *, run_id, job_id):
    from app.module_registry import ModuleId
    return await shared_snapshot(snapshot, run_id=run_id, job_id=job_id,
                                 module_id=ModuleId.VIRTUAL_CMO)


async def restore_database(*, run_id, job_id):
    from app.module_registry import ModuleId
    return await shared_database(run_id=run_id, job_id=job_id,
                                 module_id=ModuleId.VIRTUAL_CMO)


async def capture_request(request):
    from app.config import settings
    from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
    arguments = {}

    async def capture(**kwargs):
        arguments.update(kwargs)
        raise _Captured()

    try:
        await VirtualCMOExecutor(model_call=capture, numeric_quote_catalog_enabled=False).execute(request)
    except _Captured:
        pass
    if not arguments:
        raise DiagnosticError("request_not_executable")
    return Replay(await capture_wire(arguments, model=settings.DEFAULT_TEXT_MODEL_HARD), arguments)


def verify_fingerprint(replay, expected_payload_sha256):
    """Require an independently recorded full provider payload fingerprint."""
    if (not isinstance(expected_payload_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_payload_sha256) is None
            or measurement(replay.payload)["sha256"] != expected_payload_sha256):
        raise DiagnosticError("request_fingerprint_mismatch")


async def replay_once(request, replay, *, expected_payload_sha256, authorized=False):
    """One provider POST, full server validation and gates, no graph write path."""
    if authorized is not True:
        raise DiagnosticError("live_policy_rejected")
    verify_fingerprint(replay, expected_payload_sha256)
    import httpx
    from app.module_execution.executors.common import ExecutorOutputError, OutputFailureStage
    from app.module_execution.executors.virtual_cmo import VirtualCMOExecutor
    from app.module_execution.acceptance import fully_accepted
    from app.orchestration_runtime.model_adapter import production_model_call
    from app.orchestration_runtime.service import evaluate_result
    original_client = httpx.AsyncClient
    calls = 0

    class OneCallClient:
        def __init__(self, **kwargs):
            self.client = original_client(**kwargs)

        async def __aenter__(self):
            await self.client.__aenter__()
            return self

        async def __aexit__(self, *args):
            return await self.client.__aexit__(*args)

        async def post(self, url, *, headers, json):
            nonlocal calls
            # Rebuilt wire must still equal the fingerprint-verified payload.
            if measurement(json)["sha256"] != expected_payload_sha256:
                raise DiagnosticError("request_fingerprint_mismatch")
            if calls:
                raise DiagnosticError("provider_call_limit")
            calls += 1
            return await self.client.post(url, headers=headers, json=json)

    report = {"provider_calls": 0, "server_contract_valid": False,
              "quality_gates_checked": False, "quality_accepted": False}
    try:
        with patch.object(httpx, "AsyncClient", OneCallClient):
            result = await VirtualCMOExecutor(model_call=production_model_call, numeric_quote_catalog_enabled=False).execute(request)
        report["server_contract_valid"] = True
        quality = evaluate_result(request.execution_id, result, request.upstream_results)
        report["quality_gates_checked"] = True
        report["quality_accepted"] = fully_accepted(result, quality["accepted_result_ids"],
                                                   quality["accepted_claim_ids"])
        if not report["quality_accepted"]:
            report["error"] = "quality_rejected"
    except ExecutorOutputError as exc:
        report["error"] = "execution_invalid"
        if type(exc.stage) is OutputFailureStage:
            report["stage"] = exc.stage.value
        # Closed enums only; never render exceptions, raw quotes, IDs or values.
        from app.module_execution.executors.common import SemanticRule, NumericLocation, NumericContextFailureReason
        for name, enum_type in (("rule", SemanticRule), ("numeric_location", NumericLocation)):
            value = getattr(exc, name, None)
            if type(value) is enum_type:
                report[name] = value.value
        reason = getattr(exc, "numeric_context_reason", None)
        if type(reason) is NumericContextFailureReason:
            report["numeric_context_reason"] = reason.value
        for name in ("output_index", "numeric_context_index"):
            value = getattr(exc, name, None)
            if type(value) is int and 0 <= value < 10000:
                report[name] = value
    except DiagnosticError:
        report["error"] = "replay_policy_failed"
    except Exception:
        report["error"] = "provider_or_validation_failed"
    report["provider_calls"] = calls
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only VIRTUAL_CMO replay; offline by default")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path)
    source.add_argument("--database-read", action="store_true")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--authorize-one-provider-call", action="store_true")
    parser.add_argument("--expected-payload-sha256")
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)
    if args.authorize_one_provider_call and not args.expected_payload_sha256:
        print('{"error":"live_policy_rejected"}')
        return 2
    if not args.database_read and not args.authorize_one_provider_call:
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
        replay = await capture_request(request)
        if args.expected_payload_sha256:
            verify_fingerprint(replay, args.expected_payload_sha256)
        report = metadata(replay)
        report["historical_fidelity"] = "current_builders_current_accepted_graph_not_original_dispatch_snapshot"
        report["read_only"] = True
        report["provider_calls"] = 0
        if args.authorize_one_provider_call:
            report["replay"] = await replay_once(request, replay,
                expected_payload_sha256=args.expected_payload_sha256, authorized=True)
        print(compact(report))

    try:
        asyncio.run(execute())
    except Exception:
        print('{"error":"diagnostic_failed"}')
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


