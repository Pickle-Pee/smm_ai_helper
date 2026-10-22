"""Controlled policy at the real transport and service admission boundaries."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings, settings
from app.llm import controlled_live as live
from app.llm.openai_images import generate_image
from app.llm.openai_text import chat
from app.orchestration_runtime.composition import build_production_graph_runtime
from tests.test_graph_model_adapter import install_transport
from tests.test_production_graph_worker import queue


class ReceiptRows:
    """ORM row stub; actual locking/commit behavior is tested on PostgreSQL."""
    def __init__(self):
        self.ledger = SimpleNamespace(workflow_type=live.WORKFLOW, status="ready",
            input_json={"model": settings.DEFAULT_TEXT_MODEL_HARD},
            state_json={"calls": 0, "mentor": 0, "graph_run": None})
        self.artifacts = {}

    def sessions(self):
        rows = self
        @asynccontextmanager
        async def begin():
            yield
        @asynccontextmanager
        async def connection():
            async def scalar(query):
                return rows.ledger if query.column_descriptions[0]["entity"].__name__ == "MarketingRun" else rows.artifacts.get(
                    query.compile().params["artifact_key_1"])
            def add(row):
                rows.artifacts[row.artifact_key] = row
            yield SimpleNamespace(begin=begin, execute=AsyncMock(), scalar=scalar, add=add)
        return connection()


def payload():
    return {"model": settings.DEFAULT_TEXT_MODEL_HARD, "max_output_tokens": 4000, "input": []}


def test_settings_fail_closed_outside_explicit_staging():
    args = dict(DATABASE_URL="postgresql+asyncpg://offline", TELEGRAM_BOT_TOKEN="offline", OPENAI_API_KEY="offline")
    assert not Settings(_env_file=None, **args).CONTROLLED_LIVE_ENABLED
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **args, CONTROLLED_LIVE_ENABLED=True)
    assert Settings(_env_file=None, **args, CONTROLLED_LIVE_ENABLED=True,
                    DEPLOYMENT_ENVIRONMENT="staging").CONTROLLED_LIVE_ENABLED


def test_only_controlled_composition_disables_graph_recovery(monkeypatch):
    assert build_production_graph_runtime(queue=queue()).service.max_attempts == 3
    monkeypatch.setattr(settings, "CONTROLLED_LIVE_ENABLED", True)
    service = build_production_graph_runtime(queue=queue()).service
    assert service.max_attempts == 1 and service.controlled_live


@pytest.mark.parametrize("mode", ["timeout", "lost_response", "cancel", "incomplete", "schema", "success"])
def test_real_transport_one_post_and_durable_gate_after_restart(monkeypatch, mode):
    async def exercise():
        rows = ReceiptRows()
        monkeypatch.setattr(settings, "CONTROLLED_LIVE_ENABLED", True)
        monkeypatch.setattr(live, "admission", lambda: live.ControlledLiveAdmission(rows.sessions))
        calls = []
        def respond(request):
            calls.append(request)
            if mode == "timeout":
                raise httpx.ReadTimeout("private", request=request)
            if mode == "lost_response":
                raise httpx.ReadError("private", request=request)
            if mode == "cancel":
                raise asyncio.CancelledError()
            if mode == "incomplete":
                return httpx.Response(200, json={"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}})
            if mode == "schema":
                return httpx.Response(400, json={"error": {"param": "text.format", "code": "unsupported_value"}})
            return httpx.Response(200, json={"output_text": "accepted"})
        install_transport(monkeypatch, respond)
        async def call(key):
            with live.provider_operation("mentor", "run", key):
                return await chat(messages=[], model=settings.DEFAULT_TEXT_MODEL_HARD)  # legacy caller, retries=8
        if mode == "success":
            assert (await call("one"))[0] == "accepted"
        else:
            with pytest.raises(BaseException):
                await call("one")
        assert len(calls) == 1
        # Factory constructs a new admission object every time, over retained rows.
        with pytest.raises(live.ControlledLiveBlocked):
            await call("one")
        assert len(calls) == 1
        if mode == "success":
            assert (await call("two"))[0] == "accepted"
            assert len(calls) == 2
        else:
            assert rows.ledger.status == "blocked"
            assert next(iter(rows.artifacts.values())).payload_json["state"] == "unknown"
            with pytest.raises(live.ControlledLiveBlocked):
                await call("two")

    asyncio.run(exercise())


def test_crash_after_committed_reservation_and_budget_caps():
    async def exercise():
        rows = ReceiptRows()
        gate = live.ControlledLiveAdmission(rows.sessions)
        with live.provider_operation("intent", "one"):
            await gate.reserve(payload())
        # No finish: process death leaves reservation in_flight, never reclaimable.
        with live.provider_operation("intent", "two"), pytest.raises(live.ControlledLiveBlocked):
            await live.ControlledLiveAdmission(rows.sessions).reserve(payload())
        for kind, count in (("mentor", 7), ("intent", 15)):
            rows = ReceiptRows()
            gate = live.ControlledLiveAdmission(rows.sessions)
            for index in range(count):
                with live.provider_operation(kind, index):
                    receipt = await gate.reserve(payload())
                await gate.finish(receipt, success=True)
            with live.provider_operation(kind, count), pytest.raises(live.ControlledLiveBlocked, match="budget_exhausted"):
                await gate.reserve(payload())
            assert len(rows.artifacts) == count
    asyncio.run(exercise())


def test_unscoped_and_image_calls_fail_before_http(monkeypatch):
    monkeypatch.setattr(settings, "CONTROLLED_LIVE_ENABLED", True)
    monkeypatch.setattr(httpx, "AsyncClient", Mock(side_effect=AssertionError("HTTP forbidden")))
    with pytest.raises(live.ControlledLiveBlocked):
        live.current_operation()
    with pytest.raises(live.ControlledLiveBlocked):
        asyncio.run(generate_image("x", "1024x1024", "gpt-image-1"))


def test_payload_bounds_reject_before_database():
    gate = live.ControlledLiveAdmission(Mock(side_effect=AssertionError("database forbidden")))
    for updates in ({"model": "other"}, {"max_output_tokens": 16001}, {"input": ["x" * live.MAX_PAYLOAD_BYTES]}):
        with live.provider_operation("intent", "one"), pytest.raises(live.ControlledLiveBlocked):
            asyncio.run(gate.reserve({**payload(), **updates}))


def test_graph_call_identity_survives_new_attempt_and_limits_strategy(monkeypatch):
    async def exercise():
        rows = ReceiptRows()
        gate = live.ControlledLiveAdmission(rows.sessions)
        graph = {"correlation_state": "graph", "job_id": "job.one", "run_id": "run.one"}
        monkeypatch.setattr(live, "correlation_fields", lambda: graph)
        receipt = await gate.reserve(payload())
        await gate.finish(receipt, success=True)
        with pytest.raises(live.ControlledLiveBlocked, match="already_attempted"):
            await live.ControlledLiveAdmission(rows.sessions).reserve(payload())
        graph["job_id"] = "job.two"
        receipt = await gate.reserve(payload())
        await gate.finish(receipt, success=True)
        graph["run_id"] = "run.two"
        with pytest.raises(live.ControlledLiveBlocked, match="strategy_limit"):
            await gate.reserve(payload())
        graph["run_id"] = "run.one"
        rows.ledger.input_json = {"model": "changed-model"}
        with pytest.raises(live.ControlledLiveBlocked):
            await gate.reserve(payload())
    asyncio.run(exercise())
