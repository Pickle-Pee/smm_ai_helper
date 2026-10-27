"""Durable source draft -> fresh Dispatcher -> authenticated API -> captured provider."""
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram import Bot, types
from sqlalchemy import delete

from app.config import settings
from app.marketing_copilot.api_errors import CopilotAPIError
from app.marketing_copilot.contracts import IntentKind
from app.marketing_copilot.production import build_production_copilot_api
from app.models import MarketingRun, Task
from app.routers.projects import router
from app.services.project_context_service import ProjectContextService
from app.services.project_history_service import ProjectHistoryService
from bot import copilot_flow, project_navigation as nav
from bot.copilot_client import CopilotClient
from bot.handlers import chat
from tests.postgresql_support import mvp_database
from tests.test_copilot_api import application, headers, queue
from tests.test_copilot_application import intent_model
from tests.test_module_executors import FakeModel, analyzer
from tests.test_project_context_postgresql import seed, cleanup
from tests.test_telegram_navigation import close_dispatcher, update


def test_source_selection_restart_text_reaches_provider_with_saved_provenance(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    monkeypatch.setattr(settings, "API_BASE_URL", "http://backend")
    monkeypatch.setattr(Bot, "__call__", AsyncMock(return_value=True))
    monkeypatch.setattr(chat, "_send_to_backend", AsyncMock())
    async def exercise():
        from bot.main import create_dispatcher
        actor, owner, sources = await seed(mvp_database)
        model = intent_model(IntentKind.CONVERSATION)
        def runtime():
            return build_production_copilot_api(sessions=mvp_database, queue=queue(),
                intent_model=model, module_model=FakeModel(), analyzer=analyzer())
        app = application(runtime())
        app.include_router(router)
        original_http = httpx.AsyncClient
        def transport(**kwargs):
            return original_http(transport=httpx.ASGITransport(app=app), **kwargs)
        monkeypatch.setattr(httpx, "AsyncClient", transport)
        monkeypatch.setattr(copilot_flow, "client", CopilotClient())
        dp = bot = None
        try:
            dp, bot = create_dispatcher(), Bot("123456:offline-token")
            callback = types.Update(update_id=1, callback_query=types.CallbackQuery(id="source",
                from_user=types.User(id=actor, first_name="User", is_bot=False), chat_instance="private",
                data=nav.callback("n", sources[0], 0), message=types.Message(message_id=1,
                    date=datetime.now(timezone.utc), chat=types.Chat(id=actor, type="private"),
                    from_user=types.User(id=bot.id, first_name="Bot", is_bot=True))))
            await dp.feed_update(bot, callback)
            assert model.await_count == 0
            await close_dispatcher(dp, bot)
            dp = bot = None
            # Lose the entire in-memory FSM and backend service instances.
            app.state.copilot_api = runtime()
            dp, bot = create_dispatcher(), Bot("123456:offline-token")
            await dp.feed_update(bot, update(2, "Обсудим новую задачу", actor=actor))
            assert model.await_count == 1
            assembled = model.call_args.kwargs["text"]
            assert "Обсудим новую задачу" in assembled
            assert "Business_A_ONLY" in assembled and "Business_B_ONLY" not in assembled
            assert sources[0] in assembled and "saved_source_reference_unverified" in assembled
            chat._send_to_backend.assert_awaited_once()
            assert chat._send_to_backend.call_args.kwargs["request_key"] == f"tg:{actor}:{actor}:2"
            assert chat._send_to_backend.call_args.args[1] == assembled
            assert chat._send_to_backend.call_args.kwargs["context_version"] == 1
            await close_dispatcher(dp, bot)
            dp = bot = None
            app.state.copilot_api = runtime()
            dp, bot = create_dispatcher(), Bot("123456:offline-token")
            await dp.feed_update(bot, update(2, "Обсудим новую задачу", actor=actor))
            assert model.await_count == 1  # same exact source, fingerprint and durable replay
            # The source belongs only to that update, not every following message.
            await dp.feed_update(bot, update(3, "Совсем другой вопрос", actor=actor))
            assert model.await_count == 2
            assert "Business_A_ONLY" not in model.call_args.kwargs["text"]
        finally:
            if dp is not None:
                await close_dispatcher(dp, bot)
            async with mvp_database() as db, db.begin():
                await db.execute(delete(MarketingRun).where(MarketingRun.user_id == owner))
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())


def test_source_draft_owner_deletion_switch_and_exact_update_isolation(mvp_database):
    async def exercise():
        actor, owner, sources = await seed(mvp_database)
        def runtime():
            return ProjectContextService(mvp_database, ProjectHistoryService(mvp_database))
        key = f"tg:{actor}:{actor}:11"
        try:
            with pytest.raises(CopilotAPIError) as foreign:
                await runtime().switch(actor + 1, actor + 1, 0, source_public_id=sources[0])
            assert foreign.value.status == 404
            await runtime().switch(actor, actor, 0, source_public_id=sources[0])
            first = await runtime().assemble_draft(actor, actor, 1, key, "Новая задача")
            assert await runtime().assemble_draft(actor, actor, 1, key, "Новая задача") == first
            with pytest.raises(CopilotAPIError) as changed:
                await runtime().assemble_draft(actor, actor, 1, key, "Другой текст")
            assert changed.value.code == "request_conflict"
            with pytest.raises(CopilotAPIError):
                await runtime().assemble_draft(actor, actor, 1, f"tg:{actor}:{actor}:12", "Следующая задача")
            await runtime().switch(actor, actor, 1, sources[1])
            with pytest.raises(CopilotAPIError) as stale:
                await runtime().assemble_draft(actor, actor, 1, key, "Новая задача")
            assert stale.value.code == "stale_context"
            await runtime().switch(actor, actor, 2)
            assert "draft" not in await runtime().current(actor, actor)
            await runtime().switch(actor, actor, 3, source_public_id=sources[0])
            async with mvp_database() as db, db.begin():
                await db.execute(delete(Task).where(Task.id == int(sources[0].split(":")[1])))
            with pytest.raises(CopilotAPIError) as removed:
                await runtime().assemble_draft(actor, actor, 4, f"tg:{actor}:{actor}:13", "После удаления")
            assert removed.value.status == 404
        finally:
            async with mvp_database() as db, db.begin():
                await db.execute(delete(MarketingRun).where(MarketingRun.user_id == owner))
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())


@pytest.mark.parametrize("switch_to_project", [False, True])
def test_reserved_draft_switch_before_copilot_admission_rejects_even_omitted_version(mvp_database, monkeypatch, switch_to_project):
    from app.marketing_copilot.api_contracts import ExecuteRequest
    from app.marketing_copilot.execution_store import ExecutionStore
    from app.services.chat_execution_service import ChatExecutionService
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    async def exercise():
        actor, owner, sources = await seed(mvp_database)
        context = ProjectContextService(mvp_database, ProjectHistoryService(mvp_database))
        model = intent_model(IntentKind.CONVERSATION)
        api = build_production_copilot_api(sessions=mvp_database, queue=queue(),
            intent_model=model, module_model=FakeModel(), analyzer=analyzer())
        reached, release = asyncio.Event(), asyncio.Event()
        claim = api.executions.claim
        async def paused(owner, payload):
            reached.set()
            await release.wait()
            return await claim(owner, payload)
        monkeypatch.setattr(api.executions, "claim", paused)
        task = None
        try:
            await context.switch(actor, actor, 0, source_public_id=sources[0])
            key = f"tg:{actor}:{actor}:21"
            assembled = await context.assemble_draft(actor, actor, 1, key, "Новый запрос")
            payload = ExecuteRequest(request_key=key, message=assembled["message"], context_version=1)
            task = asyncio.create_task(api.execute(actor, payload))
            await asyncio.wait_for(reached.wait(), 5)
            await context.switch(actor, actor, 1, sources[1] if switch_to_project else None)
            release.set()
            with pytest.raises(CopilotAPIError) as stale:
                await asyncio.wait_for(task, 5)
            assert stale.value.code == "stale_context"
            # Omitting the optional client field cannot bypass a reserved draft.
            with pytest.raises(CopilotAPIError) as omitted:
                await api.execute(actor, ExecuteRequest(request_key=key, message=assembled["message"]))
            assert omitted.value.code == "stale_context"
            # Verify the actual public ErrorResponse accepts this admission code.
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as http:
                response = await http.post("/copilot/execute", headers=headers(actor),
                    json=payload.model_dump(mode="json", exclude_unset=True))
            assert response.status_code == 409 and response.json()["code"] == "stale_context"
            # A fallback client cannot replace the reserved epoch with the newly
            # read /new version, even if it omits the old client context field.
            operation = AsyncMock(return_value={"reply": "forbidden"})
            with pytest.raises(CopilotAPIError) as fallback:
                await ChatExecutionService(mvp_database).execute(actor, key,
                    {"user_id": f"tg:{actor}", "text": assembled["message"]},
                    f"tg:{actor}:new:2", operation)
            assert fallback.value.code == "stale_context"
            operation.assert_not_awaited()
            assert model.await_count == 0
            async with mvp_database() as db:
                assert await db.get(MarketingRun, ExecutionStore.identity(owner, key)) is None
        finally:
            release.set()
            if task is not None and not task.done():
                await task
            async with mvp_database() as db, db.begin():
                await db.execute(delete(MarketingRun).where(MarketingRun.user_id == owner))
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())
