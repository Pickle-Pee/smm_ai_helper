"""Offline replay, privacy, terminal runs and production wire parity."""
import asyncio
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from tools.positioning_diagnostics import (
    DiagnosticError, capture_request, live_probe, main, metadata,
    restore_database, restore_snapshot, variants,
)
from app.module_execution import ModuleExecutionRequest
from app.module_execution.executors import PositioningExecutor
from app.module_execution.executors.positioning_observation_schema import positioning_observation_schema
from app.module_registry import ModuleId
from app.orchestration_runtime.contracts import ARTIFACT_SCHEMA, JOB_KIND, WORKFLOW_TYPE, artifact_key, module_job_id
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.serialization import fingerprint, plan_to_json, result_to_json
from app.orchestration_runtime.service import GraphExecutionService, evaluate_result, routing
from tests.test_graph_model_adapter import install_transport
from tests.test_module_executors import request
from tests.test_strategy_builder import strategy_compiled, strategy_context, strategy_executors


RUN_ID = "a" * 64


def snapshot(*, upstream="none"):
    executors = strategy_executors()
    plan = strategy_compiled(strategy_context(() if upstream == "none" else ("https://synthetic.example/",)), executors)
    positioning = next(n for n in plan.nodes if n.module_id is ModuleId.POSITIONING)
    jobs, artifacts = [], []
    for node in plan.nodes:
        if node is not positioning and node not in plan.nodes[:plan.nodes.index(positioning)]:
            continue
        jid = module_job_id(RUN_ID, 1, node.node_id)
        job = {"job_id": jid, "marketing_run_id": RUN_ID, "kind": JOB_KIND,
               "workflow_step": node.node_id, "payload_json": routing(RUN_ID, 1, plan, node),
               "status": "failed", "error": "provider_transient", "result_json": None}
        if node is not positioning and upstream == "accepted":
            invocation = ModuleExecutionRequest(execution_id=jid, module_id=node.module_id, objective=node.objective,
                expected_outputs=node.expected_outputs, context_packet=node.context_packet)
            result = asyncio.run(executors.resolve(node.binding.executor_key).execute(invocation))
            quality = evaluate_result(jid, result, ())
            raw = {"schema_version": ARTIFACT_SCHEMA, "run_id": RUN_ID, "plan_revision": 1,
                   "node_id": node.node_id, "module_id": node.module_id.value,
                   "execution_result": result_to_json(result), "quality": quality}
            key = artifact_key(RUN_ID, 1, node.node_id)
            artifacts.append({"run_id": RUN_ID, "artifact_key": key, "artifact_type": ARTIFACT_SCHEMA,
                              "step": node.node_id, "payload_json": raw})
            job.update(status="succeeded", error=None, result_json={"artifact_key": key,
                "artifact_fingerprint": fingerprint(raw), "schema_version": ARTIFACT_SCHEMA})
        jobs.append(job)
    return {"schema_version": "positioning_diagnostic_snapshot.v1",
        "run": {"run_id": RUN_ID, "workflow_type": WORKFLOW_TYPE, "status": "failed"},
        "plan_record": {"run_id": RUN_ID, "revision": 1, "status": "active",
            "source_plan_id": plan.source_plan_id, "registry_version": plan.registry_version,
            "compiled_plan_fingerprint": plan.execution_fingerprint, "compiled_plan_json": plan_to_json(plan)},
        "jobs": jobs, "artifacts": artifacts}, module_job_id(RUN_ID, 1, positioning.node_id)


@pytest.mark.parametrize("upstream", ["none", "failed", "accepted"])
def test_terminal_replay_matches_load_work_and_wire(monkeypatch, upstream):
    source, jid = snapshot(upstream=upstream)
    before = copy.deepcopy(source)
    invocation = asyncio.run(restore_snapshot(source, run_id=RUN_ID, job_id=jid))
    replay = asyncio.run(capture_request(invocation, model="gpt-5-mini"))
    assert source == before
    assert len(invocation.upstream_results) == (1 if upstream == "accepted" else 0)
    if upstream == "failed":
        assert "optional_node_failed" in invocation.context_packet.open_questions[-1]
    report = metadata(replay)
    assert report["core_copies"] == 1 and report["core_sections_count"] == 59
    # Current runtime instruction golden; historical incident measurements are unchanged.
    assert report["components"]["instructions"] == {"bytes": 53992,
        "sha256": "7239deef6edf0d3f91079df55cc18d90c182d4b9de11e2567211a568a0c0a8a0"}
    assert report["output_fields_count"] == 16 and report["facts_count"] > 0
    assert report["evidence_ids_count"] == report["facts_count"]
    assert "Supplied" not in json.dumps(report)

    # Feed the same SELECT-backed snapshot into production load_work, bypassing
    # only its lease check. Everything after _active is the real production path.
    plan = source["plan_record"]["compiled_plan_json"]
    from app.orchestration_runtime.serialization import plan_from_json
    compiled = plan_from_json(plan)
    accepted = {u.producer_node_id: u.result for u in invocation.upstream_results}
    from app.models import JobStatus
    jobs = {row["workflow_step"]: SimpleNamespace(status=JobStatus(row["status"]), error=row["error"])
            for row in source["jobs"]}

    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        def begin(self): return self

    graph = GraphExecutionService(sessions=Session, executors=strategy_executors())
    graph._active = AsyncMock(return_value=True)
    graph._plan = AsyncMock(return_value=(1, compiled))
    graph._graph_state = AsyncMock(return_value=(jobs, accepted))
    _, production_request = asyncio.run(graph.load_work(SimpleNamespace(
        run_id=RUN_ID, job_id=jid, node_id=next(n.node_id for n in compiled.nodes if n.module_id is ModuleId.POSITIONING))))
    assert production_request == invocation

    from app.config import settings
    monkeypatch.setattr(settings, "DEFAULT_TEXT_MODEL_HARD", "gpt-5-mini")
    calls = []
    def respond(wire):
        calls.append(json.loads(wire.content))
        return httpx.Response(200, json={"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
            "output": [], "usage": {"input_tokens": 0, "output_tokens": 0, "output_tokens_details": {"reasoning_tokens": 0}}})
    install_transport(monkeypatch, respond)
    from app.llm.openai_text import ModelResponseError
    with pytest.raises(ModelResponseError):
        asyncio.run(PositioningExecutor(model_call=production_model_call).execute(production_request))
    # The diagnostic control retains canonical kinds; production intentionally
    # excludes generated OBS without changing any other serialized argument.
    expected = copy.deepcopy(replay.payload)
    expected["text"]["format"]["schema"] = positioning_observation_schema(expected["text"]["format"]["schema"])
    assert calls == [expected]
    assert set(calls[0]) == {"model", "input", "reasoning", "max_output_tokens", "text"}
    assert calls[0]["model"] == "gpt-5-mini"
    assert [v["role"] for v in calls[0]["input"]] == ["system", "user"]
    assert calls[0]["reasoning"] == {"effort": "low"}
    assert calls[0]["max_output_tokens"] == 16000
    assert calls[0]["text"]["format"]["strict"] is True
    assert calls[0]["text"]["format"]["name"] == "module_output"


@pytest.mark.parametrize("corruption", ["plan", "routing", "quality", "fingerprint", "duplicate", "scope"])
def test_replay_rejects_untrusted_snapshot(corruption):
    source, jid = snapshot(upstream="accepted")
    if corruption == "plan": source["plan_record"]["compiled_plan_fingerprint"] = "bad"
    if corruption == "routing": source["jobs"][0]["payload_json"]["module_id"] = "POSITIONING"
    if corruption == "quality":
        source["artifacts"][0]["payload_json"]["quality"]["accepted_claim_ids"] = []
        source["jobs"][0]["result_json"]["artifact_fingerprint"] = fingerprint(source["artifacts"][0]["payload_json"])
    if corruption == "fingerprint": source["jobs"][0]["result_json"]["artifact_fingerprint"] = "bad"
    if corruption == "duplicate": source["artifacts"].append(copy.deepcopy(source["artifacts"][0]))
    if corruption == "scope": source["jobs"][0]["marketing_run_id"] = "b" * 64
    with pytest.raises(ValueError):
        asyncio.run(restore_snapshot(source, run_id=RUN_ID, job_id=jid))


def test_offline_cli_no_network_safe_output(tmp_path, monkeypatch, capsys, caplog):
    source, jid = snapshot()
    path = tmp_path / "private.diagnostic-snapshot.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    def forbidden(*args, **kwargs):
        raise AssertionError("network attempted")
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    import app.db
    monkeypatch.setattr(app.db, "AsyncSessionLocal", forbidden)
    from app.config import settings
    original_model = settings.DEFAULT_TEXT_MODEL_HARD
    previous = __import__("logging").root.manager.disable
    try:
        assert main(["--snapshot", str(path), "--run-id", RUN_ID, "--job-id", jid]) == 0
        output = capsys.readouterr().out
        assert "Supplied" not in output and '"properties":{' not in output and "offline" not in output
        assert not caplog.text
        assert json.loads(output)["components"]["instructions"]["bytes"] > 50000
        assert settings.DEFAULT_TEXT_MODEL_HARD == original_model
        path.write_text('{"SECRET": "broken"}', encoding="utf-8")
        assert main(["--snapshot", str(path), "--run-id", RUN_ID, "--job-id", jid]) == 1
        assert capsys.readouterr().out == '{"error":"diagnostic_failed"}\n'
    finally:
        __import__("logging").disable(previous)


def test_db_reader_sets_read_only_before_select(monkeypatch):
    from tools import positioning_diagnostics as diagnostic
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
    monkeypatch.setattr(diagnostic, "restore", replacement)
    assert asyncio.run(restore_database(run_id=RUN_ID, job_id="test")) == "restored"
    assert statements[0] == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    assert "FOR UPDATE" not in " ".join(statements)
    replacement.assert_awaited_once()


def test_matrix_changes_only_one_component():
    replay = asyncio.run(capture_request(request(ModuleId.POSITIONING), model="gpt-5-mini"))
    before = copy.deepcopy(replay.payload)
    matrix = variants(replay, alternate_model="gpt-5")
    assert matrix["baseline"] == before
    for case, path in (("no_core", "input"), ("small_context", "input"), ("simple_schema", "text"), ("alternate_model", "model")):
        assert {k for k in before if matrix[case][k] != before[k]} == {path}
        assert matrix[case]["max_output_tokens"] == 16000
    assert replay.payload == before


@pytest.mark.parametrize("opt_in,cases,limit", [
    (False, ["baseline"], 1), (True, ["baseline"] * 2, 2),
    (True, ["baseline"], 5), (True, [], 1), (True, ["baseline", "no_core"], 1),
])
def test_live_guard_rejects_before_constructing_client(monkeypatch, opt_in, cases, limit):
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: pytest.fail("client constructed"))
    with pytest.raises(DiagnosticError):
        asyncio.run(live_probe({"baseline": {}}, cases=cases, max_calls=limit, opt_in=opt_in))


@pytest.mark.parametrize("flags", [
    ["--case", "baseline"], ["--live"], ["--live", "--case", "baseline", "--max-calls", "5"],
    ["--live", "--case", "alternate_model", "--max-calls", "1"],
])
def test_cli_live_guard_precedes_snapshot_access(flags, capsys):
    import logging
    previous = logging.root.manager.disable
    try:
        assert main(["--snapshot", "nonexistent.diagnostic-snapshot.json", "--run-id", RUN_ID,
                     "--job-id", "test", *flags]) == 2
        assert capsys.readouterr().out == '{"error":"live_policy_rejected"}\n'
    finally:
        logging.disable(previous)


def test_live_one_post_no_retry_no_content(monkeypatch):
    replay = asyncio.run(capture_request(request(ModuleId.POSITIONING), model="gpt-5-mini"))
    calls = []
    def respond(wire):
        calls.append(wire)
        return httpx.Response(200, headers={"x-request-id": "req_synthetic"}, json={"status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"}, "output": [], "output_text": "SECRET",
            "usage": {"input_tokens": 0, "output_tokens": 0, "output_tokens_details": {"reasoning_tokens": 0}}})
    install_transport(monkeypatch, respond)
    result = asyncio.run(live_probe(variants(replay), cases=["baseline"], max_calls=1, opt_in=True))
    assert len(calls) == 1 and "SECRET" not in json.dumps(result)
    assert result[0]["output_items_count"] == 0
    assert result[0]["request_id"] == "req_synthetic"
    assert result[0]["input_tokens"] == result[0]["output_tokens"] == result[0]["reasoning_tokens"] == 0


@pytest.mark.parametrize("schema_only", [False, True])
def test_public_module_cli_offline_blocks_clients_and_hides_private_values(tmp_path, schema_only):
    source, jid = snapshot()
    snapshot_path = tmp_path / "private.diagnostic-snapshot.json"
    snapshot_path.write_text(json.dumps(source), encoding="utf-8")
    guard_dir = tmp_path / "network_guard"
    guard_dir.mkdir()
    marker = tmp_path / "network_attempt"
    (guard_dir / "sitecustomize.py").write_text(
        "import os, httpx, app.db\n"
        "from pathlib import Path\n"
        "def blocked(*args, **kwargs):\n"
        "    Path(os.environ['DIAGNOSTIC_NETWORK_MARKER']).write_text('attempt')\n"
        "    raise RuntimeError('network forbidden in offline CLI test')\n"
        "httpx.AsyncClient.__init__ = blocked\n"
        "httpx.Client.__init__ = blocked\n"
        "app.db.AsyncSessionLocal = blocked\n", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(guard_dir) + os.pathsep + str(Path(__file__).resolve().parents[1]),
               DIAGNOSTIC_NETWORK_MARKER=str(marker), OPENAI_API_KEY="CLI_PRIVATE_KEY",
               OPENAI_BASE_URL="https://provider.invalid/v1",
               DATABASE_URL="postgresql+asyncpg://offline:offline@localhost:9/offline",
               TELEGRAM_BOT_TOKEN="CLI_PRIVATE_BOT_TOKEN", POSITIONING_SCHEMA_PROJECTION_ENABLED="true")
    completed = subprocess.run(
        [sys.executable, "-m", "tools.positioning_diagnostics", "--snapshot", str(snapshot_path),
         "--run-id", RUN_ID, "--job-id", jid, *(["--schema-only"] if schema_only else [])],
        cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0
    assert not marker.exists()
    report = json.loads(completed.stdout)
    assert report["components"]["instructions"]["bytes"] == 53992
    assert report["core_copies"] == 1 and "probes" not in report
    assert report["baseline_mode"] == "original_unprojected"
    if schema_only:
        from tools.positioning_schema_diagnostics import SCHEMA_CASES
        assert set(report["matrix"]) == set(report["schema_matrix"]) == {"baseline", *SCHEMA_CASES}
    for private in ("Supplied", "CLI_PRIVATE_KEY", "CLI_PRIVATE_BOT_TOKEN", '"properties":{', "EXPERT_CORE_PRODUCTION"):
        assert private not in completed.stdout + completed.stderr
