"""Plain Telegram text carries its checked epoch into atomic Copilot admission."""
import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram import Bot
from sqlalchemy import delete, select

from app.config import settings
from app.marketing_copilot.api_contracts import ExecuteRequest
from app.marketing_copilot.api_errors import CopilotAPIError
from app.marketing_copilot.contracts import IntentKind
from app.marketing_copilot.execution_store import ExecutionStore
from app.marketing_copilot.production import build_production_copilot_api
from app.models import BrandProfile, MarketingRun
from app.routers.projects import router
from app.services.project_context_service import ProjectContextService
from app.services.project_history_service import ProjectHistoryService
from bot import copilot_flow
from bot.copilot_client import CopilotClient
from bot.handlers import chat
from tests.postgresql_support import mvp_database
from tests.test_copilot_api import application, headers, queue
from tests.test_copilot_application import intent_model
from tests.test_module_executors import FakeModel, analyzer
from tests.test_project_context_postgresql import seed, cleanup
from tests.test_telegram_navigation import close_dispatcher, update


@pytest.mark.parametrize("initial_version", [0, 1])
@pytest.mark.parametrize("transition", ["activate", "deactivate", "new", "unchanged"])
def test_plain_update_checked_epoch_reaches_durable_admission(
        mvp_database, monkeypatch, initial_version, transition):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    monkeypatch.setattr(settings, "API_BASE_URL", "http://backend")
    monkeypatch.setattr(Bot, "__call__", AsyncMock(return_value=True))
    monkeypatch.setattr(chat, "_send_to_backend", AsyncMock())

    async def exercise():
        from bot.main import create_dispatcher
        actor, owner, sources = await seed(mvp_database)
        context = ProjectContextService(mvp_database, ProjectHistoryService(mvp_database))
        interpreter, provider = intent_model(IntentKind.CONVERSATION), FakeModel()
        api = build_production_copilot_api(sessions=mvp_database, queue=queue(),
            intent_model=interpreter, module_model=provider, analyzer=analyzer())
        app = application(api)
        app.include_router(router)
        original_http = httpx.AsyncClient
        responses, captured = [], []
        async def record(response):
            if response.request.url.path == "/copilot/execute":
                await response.aread()
                responses.append(response)
        def transport(**kwargs):
            return original_http(transport=httpx.ASGITransport(app=app),
                event_hooks={"response": [record]}, **kwargs)
        monkeypatch.setattr(httpx, "AsyncClient", transport)
        monkeypatch.setattr(copilot_flow, "client", CopilotClient())
        reached, release = asyncio.Event(), asyncio.Event()
        claim = api.executions.claim
        async def paused(owner_id, payload):
            captured.append(payload)
            reached.set()
            await asyncio.wait_for(release.wait(), 10)
            return await claim(owner_id, payload)
        monkeypatch.setattr(api.executions, "claim", paused)
        dp = bot = task = None
        try:
            if initial_version:
                await context.switch(actor, actor, 0)
            dp, bot = create_dispatcher(), Bot("123456:offline-token")
            task = asyncio.create_task(dp.feed_update(bot, update(901, "A plain question", actor=actor)))
            await asyncio.wait_for(reached.wait(), 10)
            assert interpreter.await_count == 0 and provider.calls == []
            if transition in {"activate", "deactivate"}:
                await context.switch(actor, actor, initial_version, sources[0])
                if transition == "deactivate":
                    await context.switch(actor, actor, initial_version + 1)
            elif transition == "new":
                await context.switch(actor, actor, initial_version)
            release.set()
            await asyncio.wait_for(task, 10)
            original = captured[0]
            assert original.request_key == f"tg:{actor}:{actor}:901"
            if transition == "unchanged":
                assert responses[0].status_code == 200
                assert interpreter.await_count == 1
                chat._send_to_backend.assert_awaited_once()
                assert chat._send_to_backend.call_args.kwargs["context_version"] == initial_version
                # Saved replay remains readable even after selection changes.
                await context.switch(actor, actor, initial_version, sources[0])
                assert (await api.execute(actor, original)).kind == "CONVERSATION"
                assert (await api.saved_execution(actor, original.request_key)).kind == "CONVERSATION"
                assert interpreter.await_count == 1
            else:
                assert responses[0].status_code == 409
                assert responses[0].json()["code"] == "stale_context"
                # Exact original delivery retains its epoch and cannot generate.
                async with httpx.AsyncClient(base_url="http://backend") as http:
                    retry = await http.post("/copilot/execute", headers=headers(actor),
                        json=original.model_dump(mode="json", exclude_unset=True))
                assert retry.status_code == 409 and retry.json()["code"] == "stale_context"
                assert interpreter.await_count == 0
                chat._send_to_backend.assert_not_awaited()
                async with mvp_database() as db:
                    assert not (await db.scalars(select(MarketingRun).where(MarketingRun.user_id == owner))).all()
            assert original.context_version == initial_version
            assert provider.calls == []
        finally:
            release.set()
            if task:
                await asyncio.gather(task, return_exceptions=True)
            if dp:
                await close_dispatcher(dp, bot)
            async with mvp_database() as db, db.begin():
                await db.execute(delete(MarketingRun).where(MarketingRun.user_id == owner))
                await db.execute(delete(BrandProfile).where(BrandProfile.user_id == owner))
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())


def test_legacy_client_without_version_keeps_existing_admission(mvp_database):
    async def exercise():
        actor, owner, sources = await seed(mvp_database)
        context = ProjectContextService(mvp_database, ProjectHistoryService(mvp_database))
        try:
            await context.switch(actor, actor, 0, sources[0])
            token, replay = await ExecutionStore(mvp_database).claim(owner,
                ExecuteRequest(request_key=f"tg:{actor}:{actor}:902", message="Legacy request"))
            assert token and replay is None
            with pytest.raises(CopilotAPIError) as stale:
                await ExecutionStore(mvp_database).claim(owner, ExecuteRequest(
                    request_key=f"tg:{actor}:{actor}:903", message="Current client", context_version=1))
            assert stale.value.code == "stale_context"
        finally:
            async with mvp_database() as db, db.begin():
                await db.execute(delete(MarketingRun).where(MarketingRun.user_id == owner))
                await db.execute(delete(BrandProfile).where(BrandProfile.user_id == owner))
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())


@pytest.mark.parametrize("switch", [False, True])
def test_clarification_retains_original_epoch(mvp_database, monkeypatch, switch):
    from tests.test_copilot_api_postgresql import CONTEXT
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    monkeypatch.setattr(settings, "API_BASE_URL", "http://backend")
    monkeypatch.setattr(Bot, "__call__", AsyncMock(return_value=True))
    async def exercise():
        from bot.main import create_dispatcher
        actor, owner, sources = await seed(mvp_database)
        context = ProjectContextService(mvp_database, ProjectHistoryService(mvp_database))
        interpreter, provider = intent_model(IntentKind.MARKETING_STRATEGY), FakeModel()
        api = build_production_copilot_api(sessions=mvp_database, queue=queue(),
            intent_model=interpreter, module_model=provider, analyzer=analyzer())
        app = application(api)
        app.include_router(router)
        original_http = httpx.AsyncClient
        def transport(**kwargs):
            return original_http(transport=httpx.ASGITransport(app=app), **kwargs)
        monkeypatch.setattr(httpx, "AsyncClient", transport)
        monkeypatch.setattr(copilot_flow, "client", CopilotClient())
        real = copilot_flow.client.execute
        captured = []
        async def capture(actor_id, payload):
            captured.append(payload)
            return await real(actor_id, payload)
        monkeypatch.setattr(copilot_flow.client, "execute", capture)
        dp = bot = None
        try:
            dp, bot = create_dispatcher(), Bot("123456:offline-token")
            async with mvp_database() as db, db.begin():
                db.add(BrandProfile(user_id=owner, extra_json={k: v for k, v in CONTEXT.items() if k != "product_truth"}))
            await dp.feed_update(bot, update(910, "Build a strategy", actor=actor))
            fsm = dp.fsm.get_context(bot=bot, chat_id=actor, user_id=actor)
            pending = (await fsm.get_data())["copilot_pending"]
            assert pending["phase"] == "fields", pending
            assert pending["payload"]["context_version"] == 0
            assert interpreter.await_count == 1 and provider.calls == []
            if switch:
                await context.switch(actor, actor, 0)  # another /new, still inactive
            # Answer the real NEEDS_INPUT form through the Dispatcher. Navigation
            # rereads the new version but must not overwrite the original payload.
            mid = 911
            while pending["phase"] == "fields":
                field = pending["fields"][0]
                name = copilot_flow.render.ALIASES.get(field, field)
                await dp.feed_update(bot, update(mid, CONTEXT[name], actor=actor))
                mid += 1
                assert mid < 930
                pending = (await fsm.get_data()).get("copilot_pending")
                if pending is None:
                    break
            assert captured[-1].context_version == 0
            assert captured[-1].request_key == captured[0].request_key
            assert interpreter.await_count == 1  # saved interpretation
            if switch:
                assert pending["phase"] == "stopped"
                assert provider.calls == []
            else:
                assert pending is None and provider.calls == []
                assert (await fsm.get_data())["copilot_run"]["run_id"]
        finally:
            if dp:
                await close_dispatcher(dp, bot)
            async with mvp_database() as db, db.begin():
                await db.execute(delete(MarketingRun).where(MarketingRun.user_id == owner))
                await db.execute(delete(BrandProfile).where(BrandProfile.user_id == owner))
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())
