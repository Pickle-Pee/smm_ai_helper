"""Production startup/lifecycle guards; all external capabilities are offline."""
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.module_execution import ModuleExecutorRegistry
from app.module_execution.errors import ModuleCompatibilityError
from app.module_execution.executors import ExecutorOutputError
from app.module_registry import ModuleRegistry
from app.orchestration_runtime import composition
from app.orchestration_runtime.worker import ModuleGraphWorker, transient
from app.worker import main, run_lane
from app.workflows.queue import FIXED_WAKEUP_KEY, GRAPH_WAKEUP_KEY


def queue(key=GRAPH_WAKEUP_KEY):
    return SimpleNamespace(key=key, wake=AsyncMock(), wait=AsyncMock(), close=AsyncMock())


def test_production_composition_six_exact_bindings_without_network(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", Mock(side_effect=AssertionError("network client at startup")))
    runtime = composition.build_production_graph_runtime(queue=queue())
    assert runtime.metadata.version == "1.2.0"
    assert set(runtime.executors.executor_keys) == {
        "competitor_analysis.v1", "positioning.v1", "creator.v1",
        "market_analysis.v1", "virtual_cmo.v1", "experiments.v1",
    }
    assert runtime.service.max_attempts == 3
    assert runtime.create_worker().timeout_seconds < runtime.service.lease_seconds
    for key in runtime.executors.executor_keys:
        executor = runtime.executors.resolve(key)
        assert executor._model_call is composition.production_model_call
    competitor = runtime.executors.resolve("competitor_analysis.v1")
    market = runtime.executors.resolve("market_analysis.v1")
    assert competitor._analyzer is market._analyzer
    assert competitor._analyzer._analyzer._propagate_fetch_errors


@pytest.mark.parametrize("kwargs", [
    {"model_call": None}, {"analyzer": None}, {"model_call": object()}, {"analyzer": object()},
    {"fixed_queue_key": GRAPH_WAKEUP_KEY}, {"queue": queue(FIXED_WAKEUP_KEY)},
])
def test_missing_capabilities_and_shared_queues_fail_before_loops(kwargs):
    with pytest.raises(ValueError):
        composition.build_production_graph_runtime(**{"queue": queue(), **kwargs})


@pytest.mark.parametrize("field,value", [
    ("OPENAI_API_KEY", " "), ("DEFAULT_TEXT_MODEL_HARD", ""), ("OPENAI_BASE_URL", "/relative"),
    ("GRAPH_TIMEOUT_SECONDS", 330), ("HTTP_TIMEOUT", 330), ("HTTP_TIMEOUT", float("nan")),
])
def test_invalid_production_configuration_fails_fast(monkeypatch, field, value):
    monkeypatch.setattr(settings, field, value)
    with pytest.raises(ValueError):
        composition.build_production_graph_runtime(queue=queue())


def test_metadata_and_executor_coherence_validated(monkeypatch):
    monkeypatch.setattr(composition, "build_module_executor_registry", lambda **kw: ModuleExecutorRegistry())
    with pytest.raises(ModuleCompatibilityError):
        composition.build_production_graph_runtime(queue=queue())
    old = ModuleRegistry.load("1.1.0")
    monkeypatch.setattr(ModuleRegistry, "load", lambda *args: old)
    with pytest.raises(ValueError, match="six Registry 1.2.0"):
        composition.build_production_graph_runtime(queue=queue())


def test_settings_bounds_and_legacy_fixed_concurrency():
    config = dict(DATABASE_URL="postgresql://offline", TELEGRAM_BOT_TOKEN="offline", OPENAI_API_KEY="offline",
                  WORKER_CONCURRENCY=4, HTTP_TIMEOUT=60, GRAPH_TIMEOUT_SECONDS=300, GRAPH_LEASE_SECONDS=330,
                  GRAPH_WORKER_CONCURRENCY=1)
    loaded = Settings(_env_file=None, **config)
    assert loaded.WORKER_CONCURRENCY == 4 and loaded.GRAPH_WORKER_CONCURRENCY == 1
    for updates in ({"GRAPH_WORKER_CONCURRENCY": 0}, {"GRAPH_WORKER_CONCURRENCY": 9},
                    {"GRAPH_TIMEOUT_SECONDS": 330}, {"HTTP_TIMEOUT": 300}, {"OPENAI_API_KEY": ""}):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{**config, **updates})


@pytest.mark.parametrize("status", [400, 401, 403, 404, 408, 409, 422, 429, 500, 502, 503, 504])
def test_transient_http_status_and_wrapped_equivalent(status):
    response = httpx.Response(status, request=httpx.Request("POST", "https://provider.test"))
    error = httpx.HTTPStatusError("SECRET", request=response.request, response=response)
    wrapped = RuntimeError("SECRET wrapper")
    wrapped.__cause__ = error
    assert transient(error) == transient(wrapped) == (status in {408, 429, 500, 502, 503, 504})


@pytest.mark.parametrize("error,retryable", [
    (TimeoutError(), True), (httpx.ReadTimeout(""), True), (httpx.ConnectError(""), True),
    (RuntimeError(), False), (ValueError(), False), (AssertionError(), False), (KeyError(), False),
])
def test_transient_cause_chain_and_cycles(error, retryable):
    wrapper = RuntimeError()
    wrapper.__cause__ = error
    assert transient(wrapper) is retryable
    if not retryable:
        error.__cause__ = wrapper
        assert not transient(wrapper)


@pytest.mark.parametrize("error", [ExecutorOutputError("invalid"), ModuleCompatibilityError("contract")])
def test_explicit_contract_failure_is_terminal_even_with_transient_cause(error):
    error.__cause__ = TimeoutError()
    assert not transient(error)


def test_loop_failure_isolation_scans_before_stale_hint_and_safe_logs(caplog, monkeypatch):
    # Other migration suites reconfigure logging with disable_existing_loggers.
    monkeypatch.setattr(logging.getLogger("app.worker"), "disabled", False)
    async def exercise():
        events = []
        recovered, healthy = asyncio.Event(), asyncio.Event()
        async def once(hint=None):
            events.append(hint)
            if len(events) == 1:
                raise RuntimeError("SECRET prompt https://user:password@example.com")
            if len(events) == 4:
                recovered.set()
                await asyncio.Event().wait()
            return False
        async def peer():
            healthy.set()
            await asyncio.Event().wait()
        bad = asyncio.create_task(run_lane(SimpleNamespace(once=once), queue(), lane="graph-0"))
        good = asyncio.create_task(run_lane(SimpleNamespace(once=peer), queue(), lane="fixed-0"))
        other_graph = asyncio.create_task(run_lane(SimpleNamespace(once=peer), queue(), lane="graph-1"))
        try:
            await asyncio.wait_for(healthy.wait(), 1)
            await asyncio.wait_for(recovered.wait(), 4)
            assert not good.done() and not other_graph.done()
            assert events[0] is None and events[1] is None and events[3] is None
        finally:
            for task in (bad, good, other_graph):
                task.cancel()
            await asyncio.gather(bad, good, other_graph, return_exceptions=True)
    asyncio.run(exercise())
    assert "lane=graph-0 error_type=RuntimeError" in caplog.text
    assert "SECRET" not in caplog.text and "password" not in caplog.text


@pytest.mark.parametrize("startup_failure", [False, True])
def test_main_starts_independent_counts_and_closes_both_queues(monkeypatch, startup_failure):
    monkeypatch.setattr(settings, "WORKER_CONCURRENCY", 2)
    monkeypatch.setattr(settings, "GRAPH_WORKER_CONCURRENCY", 3)
    async def exercise():
        queues, lanes = [], []
        ready = asyncio.Event()
        def queues_factory(**kwargs):
            result = queue(**kwargs)
            queues.append(result)
            return result
        def graph_factory(**kwargs):
            if startup_failure:
                raise ValueError("startup")
            return composition.build_production_graph_runtime(**kwargs)
        async def lane(worker, wakeups, *, lane):
            lanes.append((worker, wakeups, lane))
            if len(lanes) == 5:
                ready.set()
            await asyncio.Event().wait()
        monkeypatch.setattr("app.worker.run_lane", lane)
        task = asyncio.create_task(main(queue_factory=queues_factory, graph_factory=graph_factory))
        if startup_failure:
            with pytest.raises(ValueError, match="startup"):
                await task
        else:
            await asyncio.wait_for(ready.wait(), 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert sum(isinstance(w, ModuleGraphWorker) for w, _, _ in lanes) == 3
            assert all(q.key == (GRAPH_WAKEUP_KEY if name.startswith("graph") else FIXED_WAKEUP_KEY)
                       for _, q, name in lanes)
        assert len(queues) == 2
        for q in queues:
            q.close.assert_awaited_once()
    asyncio.run(exercise())


def test_architecture_worker_execution_has_no_context_acquisition_or_ingress():
    root = Path(__file__).resolve().parents[1]
    runtime = "\n".join(p.read_text(encoding="utf-8") for p in (root / "app/orchestration_runtime").glob("*.py"))
    for forbidden in ("AgentRunner", "MarketingExecutors", "product_context", "aiogram", "import bot", "marketing_copilot"):
        assert forbidden not in runtime
    for path in [root / "app/main.py", *(root / "app/routers").rglob("*.py"), *(root / "bot").rglob("*.py")]:
        if path == root / "app/routers/copilot.py":
            continue  # Dedicated HTTP contour; Telegram and legacy routes remain isolated.
        source = path.read_text(encoding="utf-8")
        assert "marketing_copilot" not in source and "orchestration_runtime" not in source
    assert FIXED_WAKEUP_KEY == "smm:marketing:wakeups:v1"
    assert GRAPH_WAKEUP_KEY == "smm:orchestration:wakeups:v1" != FIXED_WAKEUP_KEY
