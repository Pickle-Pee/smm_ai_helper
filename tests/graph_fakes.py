from dataclasses import replace

from app.marketing_orchestrator import MarketingOrchestratorPlanner, PlanningContext, RequestInterpretation
from app.marketing_orchestrator.contracts import AuthorizedContextFact, PlanningInputKey
from app.module_execution.executors import build_module_executor_registry
from app.module_registry import ModuleId, ModuleRegistry, ToolCapability
from app.orchestration_runtime import PlanCompiler
from tests.test_module_executors import FakeModel, analyzer


def registry(model=None):
    return build_module_executor_registry(model_call=model or FakeModel(use_parents=True), analyzer=analyzer())


def source_plan(scenario="competitive_positioning_v1"):
    facts = tuple(AuthorizedContextFact(
        fact_id="fact." + key.value, label=key.value,
        value="https://competitor.example/page" if key is PlanningInputKey.COMPETITOR_OR_CATEGORY_SCOPE else key.value,
        input_key=key, source="owner snapshot", confidence=0.8,
        module_relevance=frozenset({ModuleId.COMPETITOR_ANALYSIS, ModuleId.POSITIONING, ModuleId.MARKET_ANALYSIS}),
    ) for key in PlanningInputKey)
    return MarketingOrchestratorPlanner().plan(RequestInterpretation(
        requested_output="positioning", decision_goal="differentiate product", business_goal="sales",
        intent="position", object="product", depth="bounded", mode="workflow", scenario_key=scenario,
    ), PlanningContext(known_facts=facts, available_tools=frozenset({ToolCapability.SITE_FETCH})))


def compiled(executors=None):
    return PlanCompiler(ModuleRegistry.load("1.1.0"), executors or registry()).compile(source_plan())
