"""API process composition; it creates Jobs and hints, never a graph worker."""
from app.db import AsyncSessionLocal
from app.orchestration_runtime.composition import build_production_graph_runtime
from app.product_context import OwnedProductEvidenceService, build_owned_site_analyzer
from app.workflows.queue import RedisWakeups, GRAPH_WAKEUP_KEY
from .api_service import CopilotAPIService
from .factory import build_marketing_copilot_service
from .provider_adapters import application_model_call, owned_site_extractor, PublicIntentInterpreter

_DEFAULT = object()


def build_production_copilot_api(*, sessions=AsyncSessionLocal, queue=None,
        intent_model=application_model_call, module_model=_DEFAULT, analyzer=_DEFAULT,
        owned_analyzer=None, extractor=owned_site_extractor):
    queue = queue if queue is not None else RedisWakeups(key=GRAPH_WAKEUP_KEY)
    kwargs = {"queue": queue, "sessions": sessions}
    if module_model is not _DEFAULT:
        kwargs["model_call"] = module_model
    if analyzer is not _DEFAULT:
        kwargs["analyzer"] = analyzer
    graph = build_production_graph_runtime(**kwargs)
    if not callable(intent_model) or not callable(extractor):
        raise ValueError("Copilot intent and owned-site extractor capabilities are required")
    copilot = build_marketing_copilot_service(intent_model=intent_model,
        executor_registry=graph.executors, graph_service=graph.service, registry_version="1.2.0")
    copilot.interpreter = PublicIntentInterpreter(intent_model)
    acquisition = OwnedProductEvidenceService(analyzer=owned_analyzer if owned_analyzer is not None else build_owned_site_analyzer(),
                                             extractor=extractor)
    return CopilotAPIService(sessions=sessions, copilot=copilot, acquisition=acquisition, queue=queue)
