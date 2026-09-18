"""Bounded planning, explicit composition and versioned execution policy."""
import asyncio
import copy
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.marketing_orchestrator import MarketingOrchestratorPlanner, PlanningContext, RequestInterpretation
from app.marketing_orchestrator.contracts import PlanningStatus, ExecutionReadiness, Sensitivity
from app.marketing_orchestrator.strategy import SCENARIO, REQUIRED_KEYS, normalize_competitors
from app.marketing_copilot.application_contracts import CopilotRequest, ResultKind
from app.marketing_copilot.context_resolver import ContextEntry
from app.marketing_copilot.contracts import IntentKind
from app.marketing_copilot.factory import build_marketing_copilot_service
from app.module_execution.executors import build_module_executor_registry
from app.module_registry import ModuleId, ModuleRegistry, ToolCapability
from app.orchestration_runtime import PlanCompiler
from app.orchestration_runtime.contracts import NodeFailureMode, DependencyMode
from app.orchestration_runtime.serialization import plan_from_json, plan_to_json, bounded, fingerprint
from app.orchestration_runtime.errors import CompilationError, RuntimeContractError
from tests.test_module_executors import fact, analyzer
from tests.test_strategy_intelligence import IntelligenceModel
from tests.test_copilot_application import intent_model


def strategy_context(competitors=(), market=False, missing=()):
    values = [(k, "Supplied " + k) for k in REQUIRED_KEYS if k not in missing]
    if competitors:
        values.append(("competitor_urls", list(competitors)))
    if market:
        values.append(("market_sources", [{"source_reference": "Supplied study", "source_class": "EXTERNAL_PRIMARY",
                                           "excerpt": "Local businesses describe scheduling delays."}]))
    return PlanningContext(known_facts=tuple(fact(k, v, scenario_relevance=frozenset({SCENARIO})) for k, v in values),
                           available_tools=frozenset({ToolCapability.SITE_FETCH}))


def strategy_plan(context=None):
    return MarketingOrchestratorPlanner().plan(RequestInterpretation(
        requested_output="strategy", decision_goal="Grow qualified demand", business_goal="UNSPECIFIED",
        intent="MARKETING_STRATEGY", object="product", depth="bounded", mode="PLANNING_ONLY", scenario_key=SCENARIO),
        context if context is not None else strategy_context())


class StrategyModel(IntelligenceModel):
    async def __call__(self, **kwargs):
        output = json.loads(await super().__call__(**kwargs))
        data = json.loads(kwargs["text"])
        # A bounded fake cites the nearest ancestor, while the runtime must still
        # deliver full ancestor closure for the outer gate's lineage validation.
        upstream = data["upstream_results"]
        refs = [c["claim_id"] for c in upstream[-1]["result"]["normalized_result"]["claims"]][:8] if upstream else []
        for statement in output["outputs"]:
            statement["parent_claim_ids"] = refs
        for experiment in output.get("experiments", []):
            experiment["related_strategic_claim_ids"] = refs
            experiment["time_resource_constraints"] = data["context"]["constraints"]
        return json.dumps(output)


def strategy_executors(model=None):
    return build_module_executor_registry(model_call=model or StrategyModel(use_parents=True),
        analyzer=analyzer(), market_analyzer=analyzer(), registry_version="1.2.0")


def strategy_compiled(context=None, executors=None):
    return PlanCompiler(ModuleRegistry.load("1.2.0"), executors or strategy_executors()).compile(strategy_plan(context))


@pytest.mark.parametrize("count", range(4))
@pytest.mark.parametrize("market", [False, True])
def test_bounded_topology_scopes_and_policies(count, market):
    urls = tuple(f"https://competitor{i}.example/" for i in range(count))
    source = strategy_plan(strategy_context(urls, market))
    assert source.execution_readiness is ExecutionReadiness.PLANNING_ONLY
    assert source.planning_status is PlanningStatus.VALIDATED
    compiled = strategy_compiled(strategy_context(urls, market))
    assert len(compiled.nodes) == count + market + 3 <= 7
    assert compiled.schema_version == "compiled_execution_plan.v2" and compiled.registry_version == "1.2.0"
    assert plan_from_json(plan_to_json(compiled)) == compiled
    assert [n.node_id for n in compiled.nodes[-3:]] == ["positioning", "virtual_cmo", "experiments"]
    roots = compiled.nodes[:-3]
    for node in roots:
        assert not node.dependency_node_ids and node.failure_mode is NodeFailureMode.OPTIONAL
        assert not node.context_packet.upstream_findings
        if node.module_id is ModuleId.COMPETITOR_ANALYSIS:
            sources = [f.value for f in node.context_packet.known_facts if f.label == "competitor_url"]
            assert sources == [urls[int(node.node_id[-1]) - 1]]
            assert all(f.label not in {"competitor_urls", "market_sources"} for f in node.context_packet.known_facts)
    assert all(n.failure_mode is NodeFailureMode.REQUIRED for n in compiled.nodes[-3:-1])
    assert compiled.nodes[-1].failure_mode is NodeFailureMode.OPTIONAL
    assert all(e.mode is (DependencyMode.OPTIONAL_CONTRIBUTOR if e.downstream_node_id == "positioning" else DependencyMode.HARD)
               for e in compiled.dependencies)


def test_normalization_identity_is_order_and_duplicate_independent():
    urls = ("HTTPS://B.EXAMPLE:443", "http://A.EXAMPLE:80/path#fragment", "https://b.example/")
    canonical = ("http://a.example/path", "https://b.example/")
    assert normalize_competitors(urls) == canonical
    assert strategy_compiled(strategy_context(urls)) == strategy_compiled(strategy_context(canonical))


@pytest.mark.parametrize("urls", [("ftp://example.com",), ("https://user:secret@example.com",),
    ("https://example.com:bad",), ("https://example.com/a b",), ("https://example.com/" + "x" * 2048,),
    tuple(f"https://c{i}.example" for i in range(4)), "https://example.com", ("https://",)])
def test_invalid_competitors_are_rejected_without_fetch(urls):
    with pytest.raises(ValueError):
        normalize_competitors(urls)


def test_all_missing_first_party_inputs_are_grouped_and_empty_secret_unauthorized_do_not_count():
    plan = strategy_plan(PlanningContext())
    assert {q.input_key.value for q in plan.blocking_questions} == set(REQUIRED_KEYS)
    assert plan.planning_status is PlanningStatus.BLOCKED
    context = strategy_context()
    for invalid in (replace(context.known_facts[0], value=""),
                    replace(context.known_facts[0], authorized=False),
                    replace(context.known_facts[0], sensitivity=Sensitivity.SECRET)):
        plan = strategy_plan(replace(context, known_facts=(invalid, *context.known_facts[1:])))
        assert [q.input_key.value for q in plan.blocking_questions] == ["business_goal"]


def test_v1_and_v2_strict_shapes_and_explicit_version():
    from tests.graph_fakes import compiled
    old = plan_to_json(compiled())
    assert plan_to_json(plan_from_json(old)) == old
    assert "failure_mode" not in old["nodes"][0]
    changed = copy.deepcopy(old)
    changed["nodes"][0]["failure_mode"] = "REQUIRED"
    with pytest.raises(RuntimeContractError):
        plan_from_json(changed)
    v2 = plan_to_json(strategy_compiled())
    del v2["nodes"][0]["failure_mode"]
    with pytest.raises(RuntimeContractError):
        plan_from_json(v2)
    with pytest.raises(CompilationError):
        PlanCompiler(ModuleRegistry.load("1.1.0"), strategy_executors()).compile(strategy_plan())


@pytest.mark.parametrize("mutation", ["optional_positioning", "hard_research", "creator", "market_predecessor", "gap", "unscoped_sources"])
def test_forged_strategy_policy_or_topology_rejected_even_with_valid_fingerprint(mutation):
    raw = plan_to_json(strategy_compiled(strategy_context(("https://a.example",), True)))
    if mutation == "optional_positioning":
        raw["nodes"][-3]["failure_mode"] = "OPTIONAL"
    elif mutation == "hard_research":
        next(e for e in raw["dependencies"] if e["downstream_node_id"] == "positioning")["mode"] = "HARD"
    elif mutation == "creator":
        raw["nodes"][0]["module_id"] = "CREATOR"
    elif mutation == "market_predecessor":
        raw["nodes"][0]["dependency_node_ids"] = ["positioning"]
    elif mutation == "gap":
        raw["nodes"][1]["node_id"] = "competitor_analysis_2"
        raw["nodes"][-3]["dependency_node_ids"] = ["competitor_analysis_2", "market_analysis"]
        next(e for e in raw["dependencies"] if e["upstream_node_id"] == "competitor_analysis_1")["upstream_node_id"] = "competitor_analysis_2"
    else:
        raw["nodes"][1]["context_packet"]["known_facts"][-1]["label"] = "competitor_urls"
    raw["execution_fingerprint"] = fingerprint({k: v for k, v in raw.items() if k != "execution_fingerprint"})
    with pytest.raises(ValueError):
        plan_from_json(raw)


def test_copilot_explicit_12_starts_without_executing_and_brand_profile_context_works():
    executors = strategy_executors()
    graph = SimpleNamespace(executors=executors, start_compiled_run=AsyncMock())
    svc = build_marketing_copilot_service(intent_model=intent_model(IntentKind.MARKETING_STRATEGY),
        registry_version="1.2.0", executor_registry=executors, graph_service=graph)
    context = strategy_context()
    entries = tuple(ContextEntry(f.input_key.value if f.input_key else f.label, f) for f in context.known_facts)
    output = asyncio.run(svc.execute(CopilotRequest(actor_id=1, request_id="strategy", message="Strategy",
                                                    brand_profile=entries)))
    assert output.kind is ResultKind.WORKFLOW_STARTED
    graph.start_compiled_run.assert_awaited_once()
    assert not executors.resolve("virtual_cmo.v1")._model_call.calls


def test_own_url_is_not_product_truth_or_research_and_missing_keys_grouped():
    url = "https://my-company.example"
    svc = build_marketing_copilot_service(intent_model=intent_model(IntentKind.MARKETING_STRATEGY, (url,), business_goal=None),
                                         registry_version="1.2.0")
    output = asyncio.run(svc.execute(CopilotRequest(actor_id=1, request_id="strategy", message="Strategy " + url)))
    assert output.kind is ResultKind.NEEDS_INPUT
    assert len(output.clarification.alternatives) == 1
    assert set(output.clarification.alternatives[0]) == set(REQUIRED_KEYS)


def test_factory_default_stays_11_and_does_not_fallback():
    svc = build_marketing_copilot_service(intent_model=intent_model(IntentKind.MARKETING_STRATEGY))
    assert svc.metadata.version == "1.1.0"
    assert len(svc.compiler.executors.executor_keys) == 3


def test_frozen_pre_v2_plan_roundtrips_without_changing_fingerprint():
    from pathlib import Path
    raw = json.loads((Path(__file__).parent / "fixtures/compiled_execution_plan_v1.json").read_text())
    assert plan_to_json(plan_from_json(raw)) == raw
    assert plan_from_json(raw).execution_fingerprint == raw["execution_fingerprint"]


def test_market_customer_facts_are_opt_in_and_empty_sources_do_not_create_nodes(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo", lambda *_: pytest.fail("no DNS in planning"))
    context = strategy_context()
    research = fact("customer_findings", "Customers report scheduling delays", scenario_relevance=frozenset({SCENARIO}))
    assert strategy_plan(replace(context, known_facts=(*context.known_facts, research))).nodes[0].module_id is ModuleId.MARKET_ANALYSIS
    empty = fact("market_sources", [], scenario_relevance=frozenset({SCENARIO}))
    assert strategy_plan(replace(context, known_facts=(*context.known_facts, empty))).nodes[0].module_id is ModuleId.POSITIONING
    strategy_plan(strategy_context(("https://example.com",)))


def test_raw_intent_urls_do_not_become_strategy_sources_with_complete_context():
    url = "https://my-company.example"
    executors = strategy_executors()
    graph = SimpleNamespace(executors=executors, start_compiled_run=AsyncMock())
    svc = build_marketing_copilot_service(intent_model=intent_model(IntentKind.MARKETING_STRATEGY, (url,)),
        registry_version="1.2.0", executor_registry=executors, graph_service=graph)
    entries = tuple(ContextEntry(f.input_key.value, f) for f in strategy_context().known_facts)
    output = asyncio.run(svc.execute(CopilotRequest(actor_id=1, request_id="urls", message="Strategy " + url,
                                                    current_request=entries)))
    assert output.kind is ResultKind.WORKFLOW_STARTED
    assert len(graph.start_compiled_run.call_args.kwargs["plan"].nodes) == 3


def test_invalid_competitor_scope_returns_safe_needs_input_without_start():
    executors = strategy_executors()
    graph = SimpleNamespace(executors=executors, start_compiled_run=AsyncMock())
    svc = build_marketing_copilot_service(intent_model=intent_model(IntentKind.MARKETING_STRATEGY),
        registry_version="1.2.0", executor_registry=executors, graph_service=graph)
    context = strategy_context(("https://user:secret@example.com",))
    entries = tuple(ContextEntry(f.input_key.value if f.input_key else f.label, f) for f in context.known_facts)
    output = asyncio.run(svc.execute(CopilotRequest(actor_id=1, request_id="urls", message="Strategy", current_request=entries)))
    assert output.kind is ResultKind.NEEDS_INPUT and "secret" not in str(output)
    graph.start_compiled_run.assert_not_awaited()
