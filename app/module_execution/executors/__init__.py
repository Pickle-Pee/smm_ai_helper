"""Explicit internal composition only; not imported by the base runtime or ingress."""
from app.module_execution.errors import ModuleCompatibilityError
from app.module_execution.registry import ModuleExecutorRegistry
from app.module_registry import EXECUTABLE_REGISTRY_VERSION, EXECUTION_REGISTRY_VERSIONS, ModuleRegistry

from .common import ExecutorOutputError, ModuleModelCall
from .competitor_analysis import CompetitorAnalysisExecutor, SiteAnalyzer
from .creator import CreatorExecutor
from .positioning import PositioningExecutor
from .market_analysis import MarketAnalysisExecutor
from .virtual_cmo import VirtualCMOExecutor
from .experiments import ExperimentsExecutor


def validate_executor_coherence(metadata: ModuleRegistry, executors: ModuleExecutorRegistry) -> None:
    if metadata.version not in EXECUTION_REGISTRY_VERSIONS:
        raise ModuleCompatibilityError("Composition requires an explicit approved execution Registry")
    bound = tuple(d for d in metadata.descriptors if d.execution_binding is not None)
    if set(executors.executor_keys) != {d.execution_binding.executor_key for d in bound}:
        raise ModuleCompatibilityError("Production executor inventory must exactly match approved bindings")
    for descriptor in bound:
        binding = descriptor.execution_binding
        executor = executors.resolve(binding.executor_key)
        if (executor.module_id is not descriptor.module_id or executor.contract_version != binding.contract_version
                or executor.executor_key != binding.executor_key):
            raise ModuleCompatibilityError("Executor metadata does not match exact descriptor binding")


def build_module_executor_registry(*, model_call: ModuleModelCall | None, analyzer: SiteAnalyzer | None,
                                   composer=None, registry_version=EXECUTABLE_REGISTRY_VERSION,
                                   market_analyzer: SiteAnalyzer | None = None) -> ModuleExecutorRegistry:
    metadata = ModuleRegistry.load(registry_version)
    implementations = [
        CompetitorAnalysisExecutor(model_call=model_call, analyzer=analyzer, composer=composer),
        PositioningExecutor(model_call=model_call, composer=composer),
        CreatorExecutor(model_call=model_call, composer=composer),
    ]
    if registry_version == "1.2.0":
        implementations.extend((
            MarketAnalysisExecutor(model_call=model_call, analyzer=market_analyzer, composer=composer),
            VirtualCMOExecutor(model_call=model_call, composer=composer),
            ExperimentsExecutor(model_call=model_call, composer=composer),
        ))
    registry = ModuleExecutorRegistry(implementations)
    validate_executor_coherence(metadata, registry)
    return registry


__all__ = ["build_module_executor_registry", "validate_executor_coherence", "ExecutorOutputError",
           "ModuleModelCall", "SiteAnalyzer", "CompetitorAnalysisExecutor", "PositioningExecutor", "CreatorExecutor",
           "MarketAnalysisExecutor", "VirtualCMOExecutor", "ExperimentsExecutor"]
