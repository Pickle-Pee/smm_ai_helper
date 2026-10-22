"""Committed HTTP receipts survive lost responses, races and new compositions."""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import httpx
import pytest
from sqlalchemy import select, update

from app.config import settings
from app.marketing_copilot.api_contracts import ExecuteRequest
from app.marketing_copilot.api_errors import CopilotAPIError
from app.marketing_copilot.contracts import IntentKind
from app.marketing_copilot.execution_store import ExecutionStore, RETENTION
from app.models import MarketingRun
from bot import copilot_flow as flow
from bot.copilot_client import CopilotError
from tests.postgresql_support import mvp_database
from tests.test_copilot_api import application, headers
from tests.test_copilot_api_postgresql import configured, payload, remove_actor, CONTEXT
from tests.test_module_executors import FakeModel
from tests.test_telegram_copilot import context, message
from tests.test_telegram_copilot_postgresql import wire, brand


def test_lost_http_response_retries_saved_module_without_provider(mvp_database, monkeypatch):
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        model = FakeModel()
        api = configured(mvp_database, IntentKind.POST_GENERATION, module_model=model)
        await brand(mvp_database, actor, CONTEXT)
        wire(monkeypatch, api)
        real = flow.client.execute
        requests = []
        async def lose_first(owner, request):
            result = await real(owner, request)
            requests.append(request.model_dump(mode="json"))
            if len(requests) == 1:
                raise CopilotError("unavailable")
            return result
        monkeypatch.setattr(flow.client, "execute", lose_first)
        try:
            fsm, msg = context(actor), message("Напиши пост о напоминаниях", actor=actor)
            await flow.receive(msg, fsm)
            assert len(model.calls) == 1
            pending = (await fsm.get_data())["copilot_pending"]
            assert pending["phase"] == "retry"
            cb = SimpleNamespace(data=flow.action(pending, "retry"), id="retry", from_user=SimpleNamespace(id=actor),
                                 message=msg, answer=AsyncMock())
            await flow.callback_action(cb, fsm)
            assert requests[0] == requests[1]
            assert len(model.calls) == 1
            assert any("Use the supplied product" in str(call) for call in msg.answer.call_args_list)
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


@pytest.mark.parametrize("kind", [IntentKind.POST_GENERATION, IntentKind.LEAD_FUNNEL_CALCULATION])
def test_ten_concurrent_calls_restart_payload_conflict_owner_and_recovery(mvp_database, monkeypatch, kind):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        model = FakeModel()
        api = configured(mvp_database, kind, module_model=model)
        request = payload(message="Рассчитай лиды при бюджете 100000, CPC 50 и конверсии 5%")
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                results = await asyncio.gather(*(client.post("/copilot/execute", headers=headers(actor), json=request) for _ in range(10)))
                assert {r.status_code for r in results} == {200}
                assert all(r.json() == results[0].json() for r in results)
                count = 1 if kind is IntentKind.POST_GENERATION else 0
                assert len(model.calls) == count
                conflict = await client.post("/copilot/execute", headers=headers(actor), json={**request, "context": {**request["context"], "product": "different"}})
                assert conflict.status_code == 409
                assert len(model.calls) == count
            fresh = configured(mvp_database, kind, module_model=AsyncMock(side_effect=AssertionError("must replay")))
            fresh.copilot.interpreter.interpret_request = AsyncMock(side_effect=AssertionError("must not reinterpret"))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(fresh)), base_url="http://test") as client:
                replay = await client.post("/copilot/execute", headers=headers(actor), json=request)
                assert replay.status_code == 200 and replay.json() == results[0].json()
                saved = await client.get("/copilot/executions/" + request["request_key"], headers=headers(actor))
                assert saved.status_code == 200 and saved.json() == results[0].json()
                denied = await client.get("/copilot/executions/" + request["request_key"], headers=headers(actor+1))
                assert denied.status_code == 404
        finally:
            await remove_actor(mvp_database, actor)
            await remove_actor(mvp_database, actor+1)
    asyncio.run(check())


def test_ambiguous_provider_timeout_is_not_reexecuted_after_restart(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        model = AsyncMock(side_effect=httpx.ReadTimeout("PRIVATE_PROVIDER_DETAILS"))
        api = configured(mvp_database, IntentKind.POST_GENERATION, module_model=model)
        request = payload()
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                first = await client.post("/copilot/execute", headers=headers(actor), json=request)
                assert first.status_code == 503 and "PRIVATE" not in first.text
            fresh = configured(mvp_database, IntentKind.POST_GENERATION, module_model=model)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(fresh)), base_url="http://test") as client:
                retry = await client.post("/copilot/execute", headers=headers(actor), json=request)
                assert retry.status_code == 503 and "PRIVATE" not in retry.text
                assert (await client.get("/copilot/executions/"+request["request_key"], headers=headers(actor))).status_code == 503
            assert model.await_count == 1
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


def test_provider_observes_committed_claim_without_database_row_lock(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        request = payload()
        fake = FakeModel()
        owner = None
        async def provider(**kwargs):
            # A second database connection sees and can lock the receipt while
            # the application awaits its provider: no open execution transaction.
            async with mvp_database() as session, session.begin():
                row = await session.scalar(select(MarketingRun).where(
                    MarketingRun.run_id == ExecutionStore.identity(owner, request["request_key"]))
                    .with_for_update(nowait=True))
                assert row is not None and row.status == "running"
            return await fake(**kwargs)
        api = configured(mvp_database, IntentKind.POST_GENERATION, module_model=provider)
        try:
            owner, _ = await api._identity_context(actor)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                result = await client.post("/copilot/execute", headers=headers(actor), json=request)
                assert result.status_code == 200, result.text
            assert len(fake.calls) == 1
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


def test_committed_unfinished_claim_cannot_be_stolen_and_receipts_expire(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        model = FakeModel()
        api = configured(mvp_database, IntentKind.POST_GENERATION, module_model=model)
        request = ExecuteRequest.model_validate(payload())
        try:
            owner, _ = await api._identity_context(actor)
            token, replay = await api.executions.claim(owner, request)
            assert token and replay is None
            api.executions.wait_seconds = 0
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
                retry = await client.post("/copilot/execute", headers=headers(actor), json=request.model_dump(mode="json", exclude_unset=True))
                assert retry.status_code == 503 and not model.calls
                # Simulate process death: fresh composition has the same committed claim.
                fresh = configured(mvp_database, IntentKind.POST_GENERATION, module_model=model)
                fresh.executions.wait_seconds = 0
                with pytest.raises(CopilotAPIError) as blocked:
                    await fresh.execute(actor, request)
                assert blocked.value.code == "temporarily_unavailable" and not model.calls
                # Explicitly expired receipts are outside the documented replay window.
                async with mvp_database() as session, session.begin():
                    await session.execute(update(MarketingRun).where(MarketingRun.run_id == ExecutionStore.identity(owner, request.request_key))
                        .values(created_at=datetime.utcnow() - RETENTION - timedelta(seconds=1)))
                expired = await client.get("/copilot/executions/" + request.request_key, headers=headers(actor))
                assert expired.status_code == 404
                new_request = ExecuteRequest.model_validate(payload())
                await api.executions.claim(owner, new_request)
                async with mvp_database() as session:
                    assert await session.get(MarketingRun, ExecutionStore.identity(owner, request.request_key)) is None
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())
