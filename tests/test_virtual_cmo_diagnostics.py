"""Read-only replay through actual VIRTUAL_CMO executor, adapter and graph validators."""
import asyncio
import copy
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.module_registry import ModuleId
from tests.test_experiments_diagnostics import RUN_ID, snapshot as strategy_snapshot
from tests.test_graph_model_adapter import install_transport
from tests.test_strategy_builder import StrategyModel
from tools import positioning_diagnostics as shared
from tools import virtual_cmo_diagnostics as diagnostic


def snapshot():
    source, _ = strategy_snapshot()
    source["schema_version"] = "virtual_cmo_diagnostic_snapshot.v1"
    source["artifacts"] = [a for a in source["artifacts"]
                           if a["payload_json"]["module_id"] != ModuleId.VIRTUAL_CMO.value]
    target = next(j for j in source["jobs"] if j["workflow_step"] == "virtual_cmo")
    target.update(status="failed", error="execution_invalid", result_json=None)
    return source, target["job_id"]


def restored():
    source, jid = snapshot()
    return asyncio.run(diagnostic.restore_snapshot(source, run_id=RUN_ID, job_id=jid))


def test_restore_is_read_only_and_offline_capture_no_network(monkeypatch):
    source, jid = snapshot()
    original = copy.deepcopy(source)
    def forbidden(*args, **kwargs):
        raise AssertionError("real capability used")
    import app.db
    monkeypatch.setattr(app.db, "AsyncSessionLocal", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    request = asyncio.run(diagnostic.restore_snapshot(source, run_id=RUN_ID, job_id=jid))
    assert source == original
    assert request.module_id is ModuleId.VIRTUAL_CMO
    assert [u.module_id for u in request.upstream_results] == [ModuleId.POSITIONING]
    replay = asyncio.run(diagnostic.capture_request(request))
    assert replay.payload["max_output_tokens"] == 16000
    assert "execution_invalid" not in json.dumps(request.context_packet.open_questions)
    assert source == original


@pytest.mark.parametrize("corruption", ["plan", "artifact", "quality", "dependency"])
def test_source_fingerprints_and_accepted_graph_validated_before_http(monkeypatch, corruption):
    source, jid = snapshot()
    if corruption == "plan":
        source["plan_record"]["compiled_plan_fingerprint"] = "bad"
    elif corruption == "artifact":
        source["jobs"][0]["result_json"]["artifact_fingerprint"] = "bad"
    elif corruption == "quality":
        from app.orchestration_runtime.serialization import fingerprint
        source["artifacts"][0]["payload_json"]["quality"]["accepted_claim_ids"] = []
        source["jobs"][0]["result_json"]["artifact_fingerprint"] = fingerprint(source["artifacts"][0]["payload_json"])
    else:
        source["jobs"][0].update(status="failed", result_json=None, error="execution_invalid")
        source["artifacts"] = []
    calls = []
    install_transport(monkeypatch, lambda request: calls.append(request))
    with pytest.raises(Exception):
        asyncio.run(diagnostic.restore_snapshot(source, run_id=RUN_ID, job_id=jid))
    assert calls == []


@pytest.mark.parametrize("authorized,fingerprint", [(False, "valid"), (True, "bad"), (True, None)])
def test_permission_and_payload_fingerprint_before_client(monkeypatch, authorized, fingerprint):
    request = restored()
    replay = asyncio.run(diagnostic.capture_request(request))
    expected = diagnostic.measurement(replay.payload)["sha256"] if fingerprint == "valid" else fingerprint
    def forbidden(*args, **kwargs):
        raise AssertionError("network client constructed")
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    with pytest.raises(diagnostic.DiagnosticError):
        asyncio.run(diagnostic.replay_once(request, replay,
                    expected_payload_sha256=expected, authorized=authorized))


@pytest.mark.parametrize("mode", ["valid", "schema", "semantics", "timeout", "server", "quality"])
def test_one_call_no_retry_server_validation_quality_and_safe_output(monkeypatch, mode):
    request = restored()
    replay = asyncio.run(diagnostic.capture_request(request))
    model = StrategyModel(use_parents=True)
    output = json.loads(asyncio.run(model(**replay.arguments)))
    if mode == "schema":
        output = {"PRIVATE_SOURCE_SECRET": "42 rubles"}
    elif mode == "semantics":
        output["outputs"][0]["numeric_context"] = [{"support_id": output["outputs"][0]["parent_claim_ids"][0],
                                                     "quote": "PRIVATE_SOURCE_SECRET 42 rubles"}]
    calls = []
    def respond(wire):
        calls.append(json.loads(wire.content))
        if mode == "timeout":
            raise httpx.ReadTimeout("PRIVATE_SOURCE_SECRET", request=wire)
        if mode == "server":
            return httpx.Response(503, json={"error": {"message": "PRIVATE_SOURCE_SECRET"}})
        return httpx.Response(200, json={"output_text": json.dumps(output)})
    install_transport(monkeypatch, respond)
    import app.orchestration_runtime.service as service
    gates = service.evaluate_result
    checked = []
    def evaluate(*args):
        checked.append(True)
        result = gates(*args)
        if mode == "quality":
            result["accepted_result_ids"] = []
        return result
    monkeypatch.setattr(service, "evaluate_result", evaluate)
    report = asyncio.run(diagnostic.replay_once(request, replay,
        expected_payload_sha256=diagnostic.measurement(replay.payload)["sha256"], authorized=True))
    assert calls == [replay.payload]
    assert report["provider_calls"] == 1
    assert "PRIVATE_SOURCE_SECRET" not in json.dumps(report)
    assert request.execution_id not in json.dumps(report)
    if mode in ("valid", "quality"):
        assert checked == [True] and report["server_contract_valid"]
        assert report["quality_gates_checked"]
        assert report["quality_accepted"] is (mode == "valid")
    else:
        assert not checked and not report["server_contract_valid"]
    if mode in ("schema", "semantics"):
        assert report["error"] == "execution_invalid"


def test_database_read_only_transaction_precedes_reads(monkeypatch):
    import app.db
    statements = []
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        def begin(self): return self
        async def execute(self, query): statements.append(str(query))
        async def scalar(self, query):
            statements.append(str(query))
            return RUN_ID
    monkeypatch.setattr(app.db, "AsyncSessionLocal", Session)
    monkeypatch.setattr(app.db, "engine", SimpleNamespace(dispose=AsyncMock()))
    replacement = AsyncMock(return_value="restored")
    monkeypatch.setattr(shared, "restore", replacement)
    assert asyncio.run(diagnostic.restore_database(run_id=RUN_ID, job_id="test")) == "restored"
    assert statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert "FOR UPDATE" not in " ".join(statements)
    assert replacement.call_args.kwargs["module_id"] is ModuleId.VIRTUAL_CMO


def test_cli_offline_only_safe_metadata(tmp_path, monkeypatch, capsys):
    source, jid = snapshot()
    path = tmp_path / "private.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    def forbidden(*args, **kwargs):
        raise AssertionError("real client constructed")
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    previous = logging.root.manager.disable
    try:
        assert diagnostic.main(["--snapshot", str(path), "--run-id", RUN_ID, "--job-id", jid]) == 0
        raw = capsys.readouterr().out
        report = json.loads(raw)
        assert report["provider_calls"] == 0 and report["read_only"]
        assert "Supplied" not in raw and jid not in raw and RUN_ID not in raw
        assert diagnostic.main(["--snapshot", str(path), "--run-id", RUN_ID, "--job-id", jid,
                                "--authorize-one-provider-call"]) == 2
        assert capsys.readouterr().out == '{"error":"live_policy_rejected"}\n'
    finally:
        logging.disable(previous)

def test_historical_baseline_ignores_deployment_catalog_flag(monkeypatch):
    from app.config import settings
    request = restored()
    monkeypatch.setattr(settings, "VIRTUAL_CMO_NUMERIC_QUOTE_CATALOG_ENABLED", False)
    baseline = asyncio.run(diagnostic.capture_request(request))
    monkeypatch.setattr(settings, "VIRTUAL_CMO_NUMERIC_QUOTE_CATALOG_ENABLED", True)
    current = asyncio.run(diagnostic.capture_request(request))
    assert current.payload == baseline.payload
    assert "numeric_quote_catalog" not in json.loads(current.payload["input"][1]["content"])
