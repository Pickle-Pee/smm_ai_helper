"""Actual Dispatcher -> authenticated API -> PostgreSQL -> captured Mentor packet."""
import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
from aiogram import Bot, types
from sqlalchemy import func, select

from app.config import settings
from app.marketing_copilot.contracts import IntentKind
from app.models import Job, MarketingRun
from app.routers.projects import router as project_router
from bot import backend, project_navigation as nav
from tests.postgresql_support import mvp_database
from tests.test_case_mentor import DialogueModel
from tests.test_case_mentor_dialogue_postgresql import completed_case
from tests.test_copilot_api import application, headers
from tests.test_copilot_api_postgresql import configured, remove_actor
from tests.test_strategy_builder import StrategyModel
from tests.test_telegram_navigation import close_dispatcher, update


def test_graph_switch_restart_replays_and_preserves_mentor_feedback(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(Bot, "__call__", sent)
    async def exercise():
        from bot.main import create_dispatcher
        actor = int(uuid.uuid4().hex[:12], 16)
        model = DialogueModel()
        def runtime():
            return configured(mvp_database, IntentKind.MARKETING_STRATEGY,
                module_model=StrategyModel(use_parents=True), mentor_model=model)
        api = runtime()
        app = application(api)
        app.include_router(project_router)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        async def request(method, path, owner, *, payload=None):
            response = await client.request(method, path, headers=headers(owner), json=payload)
            if response.status_code >= 400:
                raise backend.BackendError("unavailable")
            return response.json()
        monkeypatch.setattr(backend, "request", request)
        dp = bot = None
        try:
            a = await completed_case(mvp_database, api, actor,
                product="A_ONLY_TEA_STUDIO", target="Tea buyers", message="A_ONLY campaign")
            b = await completed_case(mvp_database, api, actor,
                product="B_ONLY_CAR_DEALER", target="Car buyers", message="B_ONLY campaign")
            async with mvp_database() as db:
                initial_jobs = await db.scalar(select(func.count()).select_from(Job))
                initial_runs = await db.scalar(select(func.count()).select_from(MarketingRun))
            dp, bot = create_dispatcher(), Bot("123456:offline-token")
            def callback(mid, value):
                return types.Update(update_id=mid, callback_query=types.CallbackQuery(id=str(mid),
                    from_user=types.User(id=actor, first_name="User", is_bot=False), chat_instance="private",
                    data=value, message=types.Message(message_id=mid, date=datetime.now(timezone.utc),
                        chat=types.Chat(id=actor, type="private"),
                        from_user=types.User(id=bot.id, first_name="Bot", is_bot=True))))
            # Menu/list/card/result and activation produce no Mentor provider call.
            await dp.feed_update(bot, update(1, "/start", actor=actor))
            await dp.feed_update(bot, update(2, nav.HISTORY, actor=actor))
            await dp.feed_update(bot, callback(3, nav.callback("c", "g:" + a)))
            await dp.feed_update(bot, callback(4, nav.callback("v", "g:" + a)))
            await dp.feed_update(bot, callback(5, nav.callback("a", "g:" + a, 0)))
            assert model.calls == []
            async with mvp_database() as db:
                assert await db.scalar(select(func.count()).select_from(Job)) == initial_jobs
                assert await db.scalar(select(func.count()).select_from(MarketingRun)) == initial_runs
            await dp.feed_update(bot, update(6, "Почему?", actor=actor))
            assert len(model.calls) == 1
            assert "A_ONLY_TEA_STUDIO" in model.calls[-1]["text"]
            assert "B_ONLY_CAR_DEALER" not in model.calls[-1]["text"]
            feedback = await client.post(f"/copilot/runs/{a}/mentor/feedback", headers=headers(actor), json={
                "request_key": "report", "outcome": "worked", "notes": "A_REPORT_ONLY", "metrics": ""})
            assert feedback.status_code == 200
            await dp.feed_update(bot, callback(7, nav.callback("a", "g:" + b, 1)))
            await dp.feed_update(bot, update(8, "Почему?", actor=actor))
            assert "B_ONLY_CAR_DEALER" in model.calls[-1]["text"]
            assert "A_ONLY_TEA_STUDIO" not in model.calls[-1]["text"]
            assert "A_REPORT_ONLY" not in model.calls[-1]["text"]
            await dp.feed_update(bot, callback(9, nav.callback("a", "g:" + a, 2)))
            await close_dispatcher(dp, bot)
            dp = bot = None
            app.state.copilot_api = runtime()  # backend composition restart
            dp, bot = create_dispatcher(), Bot("123456:offline-token")
            await dp.feed_update(bot, update(10, "Какие метрики?", actor=actor))
            assert len(model.calls) == 3
            packet = json.loads(model.calls[-1]["text"])
            assert packet["run_id"] == a
            assert len(packet["dialogue"]) == 1
            assert "A_REPORT_ONLY" in model.calls[-1]["text"]
            assert "B_ONLY_CAR_DEALER" not in model.calls[-1]["text"]
            await dp.feed_update(bot, update(10, "Какие метрики?", actor=actor))
            assert len(model.calls) == 3
            stale = await client.post("/projects/context", headers=headers(actor), json={
                "chat_id": actor, "expected_version": 1, "public_id": "g:" + b})
            assert stale.status_code == 409
            foreign = await client.get("/projects/items/g:" + a, headers=headers(actor + 1))
            assert foreign.status_code == 404
            listing = await client.get("/projects/history", headers=headers(actor))
            assert [item["source_type"] for item in listing.json()["items"]] == ["graph", "graph"]
            assert all("ONLY" in item["title"] for item in listing.json()["items"])
        finally:
            if dp is not None: await close_dispatcher(dp, bot)
            await client.aclose()
            await remove_actor(mvp_database, actor)
    asyncio.run(exercise())
