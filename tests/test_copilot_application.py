import asyncio
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from socket import gaierror

import pytest

from app.marketing_copilot.application_contracts import CopilotRequest, ResultKind
from app.marketing_copilot.context_resolver import ContextEntry
from app.marketing_copilot.contracts import IntentKind, ExecutionMode, CopilotContractError
from app.marketing_copilot.factory import build_marketing_copilot_service
from app.marketing_orchestrator import MarketingOrchestratorPlanner, PlanningContext, PlanningStatus, RequestInterpretation
from app.marketing_orchestrator.contracts import PlanningInputKey
from app.marketing_orchestrator.quality_gates import QualityGateEvaluator
from app.module_registry import ModuleId, ToolCapability
from app.services.safe_http import UnsafeURL
from tests.test_marketing_copilot import intent
from tests.test_module_executors import FakeModel, analyzer, facts_for_module
from tests.graph_fakes import source_plan


def intent_model(kind, urls=(), **kwargs):
    return AsyncMock(return_value=intent(kind, provided_urls=urls,
        deterministic_calculation_required=kind is IntentKind.LEAD_FUNNEL_CALCULATION, **kwargs).model_dump_json())


def entries(module):
    return tuple(ContextEntry(f.input_key.value if f.input_key else f.label,
        replace(f, module_relevance=frozenset({module}))) for f in facts_for_module(module))


def service(kind, *, urls=(), model=None, site=None, **kwargs):
    return build_marketing_copilot_service(intent_model=intent_model(kind, urls),
        module_model=model if model is not None else FakeModel(), url_analyzer=site or analyzer(), **kwargs)


def run(svc, message="Напиши пост...", **kwargs):
    return asyncio.run(svc.execute(CopilotRequest(actor_id=1, request_id="request-1", message=message, **kwargs)))


def test_direct_vertical_never_dispatches_or_starts_work():
    model = FakeModel()
    svc = service(IntentKind.LEAD_FUNNEL_CALCULATION, model=model)
    svc.dispatcher = SimpleNamespace(dispatch=AsyncMock(side_effect=AssertionError("no module")))
    svc.compiler = SimpleNamespace(compile=lambda *_: pytest.fail("no compiler"))
    output = run(svc, "Рассчитай лиды при бюджете 100000, CPC 50 и конверсии 5%")
    assert output.kind is ResultKind.DIRECT_RESULT
    assert output.decision.mode is ExecutionMode.DIRECT_TOOL
    assert output.direct_result.clicks == 2000 and output.direct_result.leads == 100
    assert not model.calls
    svc.dispatcher.dispatch.assert_not_awaited()


@pytest.mark.parametrize("kind,module", [
    (IntentKind.POST_GENERATION, ModuleId.CREATOR),
    (IntentKind.POSITIONING, ModuleId.POSITIONING),
    (IntentKind.COMPETITOR_ANALYSIS, ModuleId.COMPETITOR_ANALYSIS),
])
def test_real_single_module_vertical_and_stable_quality_ids(kind, module):
    model, site = FakeModel(), analyzer()
    svc = service(kind, model=model, site=site)
    svc.compiler = SimpleNamespace(compile=lambda *_: pytest.fail("single must not compile durable graph"))
    output = run(svc, current_request=entries(module), available_tools=frozenset({ToolCapability.SITE_FETCH}))
    replay = run(svc, current_request=entries(module), available_tools=frozenset({ToolCapability.SITE_FETCH}))
    assert output.kind is ResultKind.MODULE_RESULT
    assert output.decision.mode is ExecutionMode.SINGLE_MODULE
    assert output.module_result.module_id is module
    assert output.module_result.normalized_result == replay.module_result.normalized_result
    assert len(model.calls) == 2
    if module is ModuleId.COMPETITOR_ANALYSIS:
        assert site.analyze.await_count == 2
    else:
        site.analyze.assert_not_awaited()


def test_literal_competitor_url_reaches_analyzer_without_evidence_fabrication():
    site = analyzer()
    url = "https://competitor.example/page"
    output = run(service(IntentKind.COMPETITOR_ANALYSIS, urls=(url,), site=site),
                 "Проанализируй этого конкурента: " + url, available_tools=frozenset({ToolCapability.SITE_FETCH}))
    assert output.kind is ResultKind.MODULE_RESULT
    site.analyze.assert_awaited_once_with(url)


def test_current_url_masks_old_brand_alias():
    site = analyzer()
    url = "https://current.example/page"
    output = run(service(IntentKind.COMPETITOR_ANALYSIS, urls=(url,), site=site),
                 "Проанализируй этого конкурента: " + url,
                 brand_profile=entries(ModuleId.COMPETITOR_ANALYSIS),
                 available_tools=frozenset({ToolCapability.SITE_FETCH}))
    assert output.kind is ResultKind.MODULE_RESULT
    site.analyze.assert_awaited_once_with(url)


def test_context_precedence_and_artifact_isolation():
    from app.marketing_orchestrator import UpstreamFinding
    from tests.test_module_executors import fact
    module = ModuleId.CREATOR
    def layer(value):
        return (ContextEntry("product", replace(fact("product", value), module_relevance=frozenset({module}))),)
    model = FakeModel()
    svc = service(IntentKind.POST_GENERATION, model=model)
    facts = tuple(e for e in entries(module) if e.semantic_key != "product")
    output = run(svc, current_request=(*facts, *layer("CURRENT")), project_run=layer("PROJECT"),
                 brand_profile=layer("BRAND"), conversation=layer("CONVERSATION"),
                 authorized_upstream_findings=(UpstreamFinding("unrelated", "artifact.reference", {"artifact_id": "old-project"}),))
    assert output.kind is ResultKind.MODULE_RESULT
    sent = model.calls[0]["text"]
    assert "CURRENT" in sent
    values = [fact["value"] for fact in json.loads(sent)["context"]["known_facts"]]
    assert all(value not in values for value in ("PROJECT", "BRAND", "CONVERSATION"))
    assert "old-project" not in sent


def test_multiple_competitor_urls_require_selection():
    urls = ("https://one.example", "https://two.example")
    model = FakeModel()
    output = run(service(IntentKind.COMPETITOR_ANALYSIS, urls=urls, model=model), "Compare " + " ".join(urls))
    assert output.kind is ResultKind.NEEDS_INPUT and not model.calls


@pytest.mark.parametrize("kind", [IntentKind.LEAD_FUNNEL_CALCULATION, IntentKind.POSITIONING,
                                  IntentKind.UNSUPPORTED, IntentKind.TEXT_EDITING, IntentKind.POST_GENERATION])
def test_grouped_clarifications_no_module_model(kind):
    model = FakeModel()
    output = run(service(kind, model=model), "Нужна помощь")
    assert output.kind is ResultKind.NEEDS_INPUT
    assert output.clarification.alternatives
    assert not model.calls and output.module_result is None


def test_ambiguous_and_conversation():
    svc = service(IntentKind.CONVERSATION)
    assert run(svc).conversation_delegate
    svc.interpreter._model_call = intent_model(IntentKind.POST_GENERATION, ambiguous=True)
    assert run(svc).kind is ResultKind.NEEDS_INPUT


@pytest.mark.parametrize("error", [None, TimeoutError("private error"), UnsafeURL("private error"), gaierror("private error")])
def test_inaccessible_competitor(error):
    site = SimpleNamespace(analyze=AsyncMock(return_value=None, side_effect=error))
    model = FakeModel()
    output = run(service(IntentKind.COMPETITOR_ANALYSIS, model=model, site=site),
                 current_request=entries(ModuleId.COMPETITOR_ANALYSIS),
                 available_tools=frozenset({ToolCapability.SITE_FETCH}))
    assert output.kind is ResultKind.NEEDS_INPUT and not model.calls
    assert "private error" not in str(output)


class PartialGate:
    def evaluate(self, batch):
        evaluation = QualityGateEvaluator().evaluate(batch)
        manifest = evaluation.synthesis_manifest
        assert manifest.accepted_result_ids and manifest.accepted_claim_ids
        return SimpleNamespace(synthesis_manifest=SimpleNamespace(
            accepted_result_ids=manifest.accepted_result_ids, accepted_claim_ids=manifest.accepted_claim_ids[1:]))


def test_partial_claim_acceptance_cannot_return_success():
    output = run(service(IntentKind.POST_GENERATION, evaluator=PartialGate()), current_request=entries(ModuleId.CREATOR))
    assert output.kind is ResultKind.NEEDS_INPUT
    assert output.clarification.code == "quality_rejected" and output.module_result is None


def test_gate_rejected_result_never_exposes_payload():
    evaluator = SimpleNamespace(evaluate=lambda _: SimpleNamespace(synthesis_manifest=SimpleNamespace(
        accepted_result_ids=(), accepted_claim_ids=())))
    output = run(service(IntentKind.POST_GENERATION, evaluator=evaluator), current_request=entries(ModuleId.CREATOR))
    assert output.kind is ResultKind.NEEDS_INPUT and output.module_result is None
    assert output.clarification.code == "quality_rejected"


def test_real_gate_partial_claim_exclusion_is_not_full_execution_acceptance():
    from app.module_execution import ModuleExecutionResult
    from app.module_execution.acceptance import fully_accepted
    from app.marketing_orchestrator.quality_gates import EvidenceSourceClass
    from tests.test_quality_gate_contradictions import _case
    batch = _case(EvidenceSourceClass.FIRST_PARTY, EvidenceSourceClass.GENERIC_BENCHMARK)
    manifest = QualityGateEvaluator().evaluate(batch).synthesis_manifest
    normalized = batch.results[0]
    assert normalized.result_id in manifest.accepted_result_ids
    assert set(manifest.accepted_claim_ids) < {c.claim_id for c in normalized.claims}
    output = ModuleExecutionResult(module_id=normalized.module_id, schema_version="test.v1", payload={}, normalized_result=normalized)
    assert not fully_accepted(output, manifest.accepted_result_ids, manifest.accepted_claim_ids)


def test_request_and_result_contracts_reject_raw_payloads():
    with pytest.raises(CopilotContractError):
        CopilotRequest(actor_id=True, request_id="id", message="post")
    with pytest.raises(CopilotContractError):
        CopilotRequest(actor_id=1, request_id="id", message="post", current_request=({},))
    output = run(service(IntentKind.CONVERSATION))
    with pytest.raises(CopilotContractError):
        replace(output, module_result={})


def test_unknown_workflow_and_compiler_authority_prevent_start():
    from app.orchestration_runtime.errors import CompilationError
    svc = service(IntentKind.MARKETING_STRATEGY)
    svc.graph_service = SimpleNamespace(start_compiled_run=AsyncMock(side_effect=AssertionError("no start")))
    assert run(svc).kind is ResultKind.NEEDS_INPUT
    svc.interpreter._model_call = intent_model(IntentKind.COMPARATIVE_POSITIONING)
    from tests.test_copilot_postgresql import workflow_entries
    svc.compiler.compile = lambda *_: (_ for _ in ()).throw(CompilationError("not authorized"))
    assert run(svc, current_request=workflow_entries(), available_tools=frozenset({ToolCapability.SITE_FETCH})).kind is ResultKind.NEEDS_INPUT
    svc.graph_service.start_compiled_run.assert_not_awaited()


@pytest.mark.parametrize("scenario,fetch,has_url,expected", [
    ("competitive_positioning_v1", True, True, PlanningStatus.VALIDATED),
    ("competitive_positioning_v1", False, True, PlanningStatus.BLOCKED),
    ("competitive_positioning_v1", True, False, PlanningStatus.BLOCKED),
    ("new_positioning_v1", True, True, PlanningStatus.BLOCKED),
])
def test_competitive_fetch_replaces_evidence_requirement_only_for_new_scenario(scenario, fetch, has_url, expected):
    facts = source_plan().nodes[0].context_packet.relevant_project_context + source_plan().nodes[0].context_packet.known_facts
    facts = tuple(replace(f, value="category" if not has_url and f.input_key is PlanningInputKey.COMPETITOR_OR_CATEGORY_SCOPE else f.value)
                  for f in facts if f.input_key is not PlanningInputKey.OBSERVABLE_EVIDENCE)
    plan = MarketingOrchestratorPlanner().plan(RequestInterpretation(
        requested_output="positioning", decision_goal="differentiate", business_goal="sales", intent="compare",
        object="product", depth="workflow", mode="planning", scenario_key=scenario), PlanningContext(
            known_facts=facts, available_tools=frozenset({ToolCapability.SITE_FETCH}) if fetch else frozenset()))
    assert plan.planning_status is expected
    assert all(f.input_key is not PlanningInputKey.OBSERVABLE_EVIDENCE for n in plan.nodes
               for f in (*n.context_packet.known_facts, *n.context_packet.relevant_project_context))


def test_architecture_only_explicit_copilot_router_connects_new_ingress():
    root = Path(__file__).resolve().parents[1]
    for folder in ("app/routers", "bot", "app/services", "app/workflows"):
        for path in (root / folder).rglob("*.py"):
            if path == root / "app/routers/copilot.py":
                continue
            assert "marketing_copilot" not in path.read_text(encoding="utf-8")
    assert "marketing_copilot" not in (root / "app/worker.py").read_text(encoding="utf-8")
    for path in (root / "app/marketing_tools").glob("*.py"):
        assert "module_execution" not in path.read_text(encoding="utf-8")
    source = (root / "app/marketing_copilot/service.py").read_text(encoding="utf-8")
    for forbidden in ("AgentRunner", "MarketingExecutors", "TaskPipelineService", "app.models", "app.db"):
        assert forbidden not in source
