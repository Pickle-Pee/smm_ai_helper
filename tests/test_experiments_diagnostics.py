"""Offline EXPERIMENTS replay across production graph, adapter and schema boundaries."""
import asyncio
import copy
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from jsonschema import Draft202012Validator

from app.module_execution import ModuleExecutionRequest
from app.module_execution.executors.experiments import ExperimentsExecutor, strategic_parents
from app.module_registry import ModuleId
from app.orchestration_runtime.contracts import ARTIFACT_SCHEMA, JOB_KIND, WORKFLOW_TYPE, artifact_key, module_job_id
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.serialization import fingerprint, plan_from_json, plan_to_json, result_to_json
from app.orchestration_runtime.service import GraphExecutionService, evaluate_result, routing
from tests.test_graph_model_adapter import install_transport
from tests.test_strategy_builder import StrategyModel, strategy_compiled, strategy_context, strategy_executors
from tools import experiments_diagnostics as diagnostic

RUN_ID = "a" * 64


def snapshot(*, constraints=()):
    executors = strategy_executors()
    plan = strategy_compiled(replace(strategy_context(), constraints=constraints), executors)
    accepted, jobs, artifacts = {}, [], []
    for node in plan.nodes:
        jid = module_job_id(RUN_ID, 1, node.node_id)
        job = {"job_id": jid, "marketing_run_id": RUN_ID, "kind": JOB_KIND,
               "workflow_step": node.node_id, "payload_json": routing(RUN_ID, 1, plan, node),
               "status": "failed", "error": "provider_transient", "result_json": None}
        if node.module_id is not ModuleId.EXPERIMENTS:
            upstream = GraphExecutionService._upstream(plan, node, accepted)
            invocation = ModuleExecutionRequest(execution_id=jid, module_id=node.module_id,
                objective=node.objective, expected_outputs=node.expected_outputs,
                context_packet=node.context_packet, upstream_results=upstream)
            result = asyncio.run(executors.resolve(node.binding.executor_key).execute(invocation))
            quality = evaluate_result(jid, result, upstream)
            assert quality["accepted_claim_ids"]
            accepted[node.node_id] = result
            raw = {"schema_version": ARTIFACT_SCHEMA, "run_id": RUN_ID, "plan_revision": 1,
                   "node_id": node.node_id, "module_id": node.module_id.value,
                   "execution_result": result_to_json(result), "quality": quality}
            key = artifact_key(RUN_ID, 1, node.node_id)
            artifacts.append({"run_id": RUN_ID, "artifact_key": key, "artifact_type": ARTIFACT_SCHEMA,
                              "step": node.node_id, "payload_json": raw})
            job.update(status="succeeded", error=None, result_json={"artifact_key": key,
                "artifact_fingerprint": fingerprint(raw), "schema_version": ARTIFACT_SCHEMA})
        jobs.append(job)
    return {"schema_version": "experiments_diagnostic_snapshot.v1",
        "run": {"run_id": RUN_ID, "workflow_type": WORKFLOW_TYPE, "status": "failed"},
        "plan_record": {"run_id": RUN_ID, "revision": 1, "status": "active",
            "source_plan_id": plan.source_plan_id, "registry_version": plan.registry_version,
            "compiled_plan_fingerprint": plan.execution_fingerprint, "compiled_plan_json": plan_to_json(plan)},
        "jobs": jobs, "artifacts": artifacts}, jobs[-1]["job_id"]


def restored():
    source, jid = snapshot()
    return asyncio.run(diagnostic.restore_snapshot(source, run_id=RUN_ID, job_id=jid))


def test_failed_replay_matches_original_dispatch_and_production_wire(monkeypatch):
    source, jid = snapshot()
    before = copy.deepcopy(source)
    invocation = asyncio.run(diagnostic.restore_snapshot(source, run_id=RUN_ID, job_id=jid))
    replay = asyncio.run(diagnostic.capture_request(invocation))
    assert source == before
    assert {u.module_id for u in invocation.upstream_results} == {ModuleId.POSITIONING, ModuleId.VIRTUAL_CMO}
    assert strategic_parents(invocation)
    assert "provider_transient" not in json.dumps(invocation.context_packet.open_questions)
    compiled = plan_from_json(source["plan_record"]["compiled_plan_json"])
    accepted = {u.producer_node_id: u.result for u in invocation.upstream_results}
    from app.models import JobStatus
    # Original dispatch preceded the target's failure; load_work must see only ancestors.
    jobs = {row["workflow_step"]: SimpleNamespace(status=JobStatus(row["status"]), error=row["error"])
            for row in source["jobs"][:-1]}
    class Session:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        def begin(self): return self
    graph = GraphExecutionService(sessions=Session, executors=strategy_executors())
    graph._active = AsyncMock(return_value=True)
    graph._plan = AsyncMock(return_value=(1, compiled))
    graph._graph_state = AsyncMock(return_value=(jobs, accepted))
    _, production_request = asyncio.run(graph.load_work(SimpleNamespace(
        run_id=RUN_ID, job_id=jid, node_id=compiled.nodes[-1].node_id)))
    assert production_request == invocation
    from app.config import settings
    monkeypatch.setattr(settings, "DEFAULT_TEXT_MODEL_HARD", "gpt-5-mini")
    calls = []
    def respond(wire):
        calls.append(json.loads(wire.content))
        return httpx.Response(200, json={"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"},
            "output": [], "usage": {"input_tokens": 0, "output_tokens": 0,
                                     "output_tokens_details": {"reasoning_tokens": 0}}})
    install_transport(monkeypatch, respond)
    from app.llm.openai_text import ModelResponseError
    with pytest.raises(ModelResponseError):
        asyncio.run(ExperimentsExecutor(model_call=production_model_call).execute(production_request))
    assert calls == [replay.payload]
    assert replay.payload["max_output_tokens"] == 16000
    report = diagnostic.metadata(replay, invocation)
    assert report["components"]["instructions"]["bytes"] == 53477
    assert report["incident_comparison"]["instructions"]["matches"] is False
    assert report["support_or_branches"] == {"single": 0, "two": 1}
    assert report["experiment_design"]["strategic_parent_count"] == len(strategic_parents(invocation))
    assert report["duplication"]["fact_values_repeated_in_evidence"] > 0
    assert report["duplication"]["payload_claim_equal_fields"] > 0
    assert report["duplication"]["safe_to_remove"] is False
    for name, incident in diagnostic.INCIDENT.items():
        item = report["incident_comparison"][name]
        assert item["delta_bytes"] == item["actual_bytes"] - incident
        assert item["matches"] == (item["delta_bytes"] == 0)


@pytest.mark.parametrize("corruption", ["dependency", "quality", "fingerprint", "parent", "duplicate", "scope"])
def test_restore_rejects_corrupt_accepted_graph(corruption):
    source, jid = snapshot()
    if corruption == "dependency":
        source["jobs"][1].update(status="failed", error="provider_transient", result_json=None)
        source["artifacts"].pop()
    elif corruption == "quality":
        source["artifacts"][1]["payload_json"]["quality"]["accepted_claim_ids"] = []
        source["jobs"][1]["result_json"]["artifact_fingerprint"] = fingerprint(source["artifacts"][1]["payload_json"])
    elif corruption == "fingerprint":
        source["jobs"][1]["result_json"]["artifact_fingerprint"] = "bad"
    elif corruption == "parent":
        source["artifacts"][1]["payload_json"]["execution_result"]["normalized_result"]["claims"][0]["parent_claim_ids"] = ["clm_unknown"]
        source["jobs"][1]["result_json"]["artifact_fingerprint"] = fingerprint(source["artifacts"][1]["payload_json"])
    elif corruption == "duplicate":
        source["artifacts"].append(copy.deepcopy(source["artifacts"][0]))
    else:
        source["jobs"][0]["marketing_run_id"] = "b" * 64
    with pytest.raises(ValueError):
        asyncio.run(diagnostic.restore_snapshot(source, run_id=RUN_ID, job_id=jid))


def test_matrix_preserves_wire_and_two_branch_or_without_false_optimization():
    replay = asyncio.run(diagnostic.capture_request(restored()))
    before = copy.deepcopy(replay.payload)
    payloads, reports = diagnostic.schema_matrix(replay.payload)
    assert reports["collapse_single_support_anyof"]["available"] is True
    assert reports["collapse_single_support_anyof"]["changed"] is False
    assert "collapse_single_support_anyof" not in payloads
    for case, payload in payloads.items():
        assert {key for key in before if payload[key] != before[key]} == (set() if case == "baseline" else {"text"})
        assert {key for key in before["text"]["format"] if payload["text"]["format"][key] != before["text"]["format"][key]} <= {"schema"}
        Draft202012Validator.check_schema(payload["text"]["format"]["schema"])
    assert before == replay.payload
    assert "anyOf" in payloads["no_annotations"]["text"]["format"]["schema"]["$defs"]["ExperimentStatement"]


def test_single_branch_equivalence_is_proved_and_refuses_semantic_difference():
    from app.module_execution.executors.support_schema import support_response_schema
    from app.module_execution.executors.intelligence_schemas import ExperimentsOutput
    schema = support_response_schema(ExperimentsOutput, (), ("clm_parent",))
    wire = {"text": {"format": {"schema": schema}}}
    payloads, report = diagnostic.schema_matrix(wire)
    assert report["collapse_single_support_anyof"]["changed"] is True
    original = Draft202012Validator(schema)
    collapsed = Draft202012Validator(payloads["collapse_single_support_anyof"]["text"]["format"]["schema"])
    request = restored()
    raw = asyncio.run(StrategyModel(use_parents=True)(**asyncio.run(diagnostic.capture_request(request)).arguments))
    value = json.loads(raw)
    for statement in value["outputs"]:
        statement["evidence_ids"], statement["parent_claim_ids"] = [], ["clm_parent"]
    assert original.is_valid(value) and collapsed.is_valid(value)
    value["outputs"][0]["parent_claim_ids"] = []
    assert not original.is_valid(value) and not collapsed.is_valid(value)
    schema["$defs"]["ExperimentStatement"]["anyOf"][0]["properties"]["text"]["maxLength"] = 1
    _, report = diagnostic.schema_matrix(wire)
    assert report["collapse_single_support_anyof"]["equivalence"] == "proof_refused"
    schema["$id"] = "urn:private-schema"
    _, report = diagnostic.schema_matrix(wire)
    assert report["inline_refs"]["equivalence"] == "proof_refused"


@pytest.mark.parametrize("references", [["clm_unknown"], ["duplicate", "duplicate"]])
def test_design_schema_bounds_do_not_replace_strategic_subset_validation(references):
    invocation = restored()
    replay = asyncio.run(diagnostic.capture_request(invocation))
    raw = json.loads(asyncio.run(StrategyModel(use_parents=True)(**replay.arguments)))
    refs = [next(iter(strategic_parents(invocation)))] * 2 if references[0] == "duplicate" else references
    raw["experiments"][0]["related_strategic_claim_ids"] = refs
    assert Draft202012Validator(replay.arguments["response_schema"]).is_valid(raw)
    async def model(**kwargs): return json.dumps(raw)
    from app.module_execution.executors import ExecutorOutputError
    with pytest.raises(ExecutorOutputError):
        asyncio.run(ExperimentsExecutor(model_call=model).execute(invocation))


def test_strategic_eligibility_uses_accepted_status_authority_type_and_module():
    from app.marketing_orchestrator.quality_gates.contracts import AuthorityStatus, ClaimType, ModuleResultStatus
    invocation = restored()
    eligible = strategic_parents(invocation)
    for key in eligible:
        assert any(c.claim_id == key and c.claim_type is ClaimType.HYPOTHESIS for u in invocation.upstream_results
                   if u.module_id in (ModuleId.POSITIONING, ModuleId.VIRTUAL_CMO) for c in u.result.normalized_result.claims)
    upstream = invocation.upstream_results[0]
    def changed_request(*, module=upstream.module_id, **normalized):
        changed_result = replace(upstream.result, module_id=module,
            payload=result_to_json(upstream.result)["payload"], normalized_result=replace(
                upstream.result.normalized_result, module_id=module, **normalized))
        return replace(invocation, upstream_results=(replace(upstream, result=changed_result),))
    assert not strategic_parents(changed_request(module_status=ModuleResultStatus.BLOCKED))
    claims = tuple(replace(c, claim_type=ClaimType.RECOMMENDATION) for c in upstream.result.normalized_result.claims)
    assert not strategic_parents(changed_request(claims=claims))
    claims = tuple(replace(c, authority_status=AuthorityStatus.OUT_OF_SCOPE) for c in upstream.result.normalized_result.claims)
    assert not strategic_parents(changed_request(claims=claims))
    assert not strategic_parents(changed_request(module=ModuleId.MARKET_ANALYSIS))


def test_constraints_restored_into_context_and_local_evidence():
    source, jid = snapshot(constraints=("Only supplied resources",))
    invocation = asyncio.run(diagnostic.restore_snapshot(source, run_id=RUN_ID, job_id=jid))
    replay = asyncio.run(diagnostic.capture_request(invocation))
    data = json.loads(replay.arguments["text"])
    assert data["context"]["constraints"] == ["Only supplied resources"]
    assert any(e["input_key"] == "constraints" and e["value"] == "Only supplied resources"
               for e in data["local_evidence"])


def test_diagnostic_architecture_uses_read_only_shared_restoration():
    import ast
    source = Path(diagnostic.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"add", "add_all", "delete", "commit", "flush", "enqueue", "claim", "complete",
                 "fail", "start_run", "persist_result", "dispatch", "load_work", "_write_artifact"}
    assert not {node.func.attr for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)} & forbidden
    assert not {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} & {"JobExecution", "MarketingArtifact", "GraphExecutionService"}
    assert diagnostic.shared_snapshot.__module__ == "tools.positioning_diagnostics"
    assert diagnostic.shared_database.__module__ == "tools.positioning_diagnostics"


def test_database_forwarding_keeps_shared_read_only_transaction(monkeypatch):
    from tools import positioning_diagnostics as shared
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
    assert replacement.await_args.kwargs["module_id"] is ModuleId.EXPERIMENTS


def test_public_cli_offline_blocks_clients_and_hides_private_values(tmp_path):
    source, jid = snapshot()
    path = tmp_path / "private.diagnostic-snapshot.json"
    path.write_text(json.dumps(source), encoding="utf-8")
    guard = tmp_path / "network_guard"
    guard.mkdir()
    marker = tmp_path / "network_attempt"
    (guard / "sitecustomize.py").write_text(
        "import os, httpx, app.db\nfrom pathlib import Path\n"
        "def blocked(*args, **kwargs):\n"
        "    Path(os.environ['DIAGNOSTIC_NETWORK_MARKER']).write_text('attempt')\n"
        "    raise RuntimeError('network forbidden')\n"
        "httpx.AsyncClient.__init__ = blocked\nhttpx.Client.__init__ = blocked\n"
        "app.db.AsyncSessionLocal = blocked\n", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(guard) + os.pathsep + str(Path(__file__).resolve().parents[1]),
        DIAGNOSTIC_NETWORK_MARKER=str(marker), OPENAI_API_KEY="CLI_PRIVATE_KEY",
        OPENAI_BASE_URL="https://provider.invalid/v1", TELEGRAM_BOT_TOKEN="CLI_PRIVATE_BOT",
        DATABASE_URL="postgresql+asyncpg://offline:offline@localhost:9/offline")
    completed = subprocess.run([sys.executable, "-m", "tools.experiments_diagnostics", "--snapshot", str(path),
        "--run-id", RUN_ID, "--job-id", jid], cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert not marker.exists()
    report = json.loads(completed.stdout)
    assert "probes" not in report and report["output_budget"]["matches"]
    assert set(report["schema_matrix"]) == set(diagnostic.CASES)
    for private in ("Supplied", "CLI_PRIVATE_KEY", "CLI_PRIVATE_BOT", '"properties":{', "EXPERT_CORE_PRODUCTION"):
        assert private not in completed.stdout + completed.stderr


@pytest.mark.parametrize("flags", [["--case", "baseline"], ["--live"],
    ["--live", "--case", "baseline", "--max-calls", "5"],
    ["--live", "--case", "baseline", "--case", "baseline", "--max-calls", "2"]])
def test_live_policy_precedes_snapshot_access(flags, capsys):
    assert diagnostic.main(["--snapshot", "missing.diagnostic-snapshot.json", "--run-id", RUN_ID,
                            "--job-id", "test", *flags]) == 2
    assert capsys.readouterr().out == '{"error":"live_policy_rejected"}\n'


def test_failure_cli_report_never_contains_untrusted_values(tmp_path, capsys):
    path = tmp_path / "broken.json"
    path.write_text('{"PRIVATE_EXCEPTION_VALUE": "broken"}', encoding="utf-8")
    assert diagnostic.main(["--snapshot", str(path), "--run-id", RUN_ID, "--job-id", "test"]) == 1
    assert capsys.readouterr().out == '{"error":"diagnostic_failed"}\n'
