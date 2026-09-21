"""Explicit internal composition. No configured providers or ingress side effects."""
from app.marketing_orchestrator import MarketingOrchestratorPlanner
from app.marketing_orchestrator.quality_gates import QualityGateEvaluator
from app.marketing_tools import DeterministicToolRegistry
from app.module_execution import ModuleExecutorDispatcher
from app.module_execution.executors import build_module_executor_registry, validate_executor_coherence
from app.module_registry import ModuleRegistry
from app.orchestration_runtime.compiler import PlanCompiler
from .context_resolver import ContextResolver
from .execution_policy import ExecutionPolicy
from .interpreter import MarketingIntentInterpreter
from .orchestrator_adapter import OrchestratorAdapter
from .service import MarketingCopilotService


def build_marketing_copilot_service(*, intent_model, module_model=None, url_analyzer=None,
                                    executor_registry=None, graph_service=None, tools=None, evaluator=None,
                                    registry_version="1.1.0", market_analyzer=None):
    metadata = ModuleRegistry.load(registry_version)
    executors = executor_registry if executor_registry is not None else build_module_executor_registry(
        model_call=module_model, analyzer=url_analyzer, registry_version=registry_version,
        market_analyzer=market_analyzer)
    validate_executor_coherence(metadata, executors)
    if graph_service is not None and graph_service.executors is not executors:
        raise ValueError("Fast and durable paths must share the injected executor registry")
    return MarketingCopilotService(
        interpreter=MarketingIntentInterpreter(intent_model), resolver=ContextResolver(),
        policy=ExecutionPolicy(), adapter=OrchestratorAdapter(), planner=MarketingOrchestratorPlanner(),
        compiler=PlanCompiler(metadata, executors), metadata=metadata,
        dispatcher=ModuleExecutorDispatcher(executors), evaluator=evaluator or QualityGateEvaluator(),
        graph_service=graph_service, tools=tools or DeterministicToolRegistry(),
    )
