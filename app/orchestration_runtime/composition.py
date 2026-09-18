"""Production graph composition; construction performs no provider/network I/O."""
from dataclasses import dataclass

import httpx

from app.config import settings
from app.db import AsyncSessionLocal
from app.module_execution import ModuleExecutorRegistry
from app.module_execution.executors import build_module_executor_registry, validate_executor_coherence
from app.module_execution.executors.capabilities import build_public_site_analyzer
from app.module_registry import ModuleRegistry
from app.workflows.queue import FIXED_WAKEUP_KEY, GRAPH_WAKEUP_KEY
from .model_adapter import production_model_call
from .service import GraphExecutionService
from .worker import ModuleGraphWorker

_DEFAULT = object()


@dataclass(frozen=True)
class ProductionGraphRuntime:
    metadata: ModuleRegistry
    executors: ModuleExecutorRegistry
    service: GraphExecutionService
    timeout_seconds: int

    def create_worker(self):
        return ModuleGraphWorker(self.service, timeout_seconds=self.timeout_seconds)


def build_production_graph_runtime(*, queue, fixed_queue_key=FIXED_WAKEUP_KEY,
                                   sessions=AsyncSessionLocal, model_call=_DEFAULT, analyzer=_DEFAULT):
    """Inject capabilities for offline tests; explicit None is a startup error.

    Queues belong to the process. The existing model and URL transports own and
    close per-call clients, including on cancellation; there is no shared client.
    """
    if queue.key != GRAPH_WAKEUP_KEY or queue.key == fixed_queue_key:
        raise ValueError("Graph and fixed queues require distinct canonical keys")
    if not 0 < settings.HTTP_TIMEOUT < settings.GRAPH_TIMEOUT_SECONDS < settings.GRAPH_LEASE_SECONDS:
        raise ValueError("Require provider timeout < graph timeout < graph lease")
    if model_call is _DEFAULT:
        url = httpx.URL(settings.OPENAI_BASE_URL)
        if (not settings.OPENAI_API_KEY.strip() or not settings.DEFAULT_TEXT_MODEL_HARD.strip()
                or url.scheme not in ("http", "https") or not url.host):
            raise ValueError("Production text model capability is not configured")
        model_call = production_model_call
    if analyzer is _DEFAULT:
        analyzer = build_public_site_analyzer()
    if not callable(model_call) or not callable(getattr(analyzer, "analyze", None)):
        raise ValueError("Production graph requires model and public URL capabilities")
    metadata = ModuleRegistry.load("1.2.0")
    if metadata.version != "1.2.0" or sum(d.execution_binding is not None for d in metadata.descriptors) != 6:
        raise ValueError("Production graph requires exactly six Registry 1.2.0 bindings")
    executors = build_module_executor_registry(model_call=model_call, analyzer=analyzer,
        market_analyzer=analyzer, registry_version="1.2.0")
    validate_executor_coherence(metadata, executors)
    service = GraphExecutionService(sessions, executors=executors, queue=queue,
        lease_seconds=settings.GRAPH_LEASE_SECONDS, max_attempts=3)
    return ProductionGraphRuntime(metadata, executors, service, settings.GRAPH_TIMEOUT_SECONDS)
