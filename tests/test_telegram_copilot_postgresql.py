"""Offline Telegram -> authenticated API -> PostgreSQL -> real graph worker."""
import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.models import BrandProfile, MarketingRun, User
from app.marketing_copilot.contracts import IntentKind
from app.orchestration_runtime.worker import ModuleGraphWorker
from bot import copilot_flow as flow
from bot.copilot_client import CopilotClient
from bot.handlers.copilot import check_status
from tests.postgresql_support import mvp_database
from tests.test_copilot_api import application
from tests.test_copilot_api_postgresql import CONTEXT, configured, remove_actor
from tests.test_graph_postgresql import state as graph_state
from tests.test_module_executors import analyzer
from tests.test_product_context import OWN, PRODUCT, AUDIENCE, JOB, PRICE, LEADER, extraction
from tests.test_strategy_builder import StrategyModel
from tests.test_telegram_copilot import message, context, click, text_sent


def wire(monkeypatch, api):
    original = httpx.AsyncClient
    app = application(api)
    calls = []
    def factory(**kwargs):
        return original(transport=httpx.ASGITransport(app=app), **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", factory)
    monkeypatch.setattr(settings, "API_BASE_URL", "http://backend")
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    client = CopilotClient()
    original_execute = client.execute
    async def execute(actor, payload):
        calls.append(payload)
        return await original_execute(actor, payload)
    client.execute = execute
    monkeypatch.setattr(flow, "client", client)
    return calls


async def brand(db, actor, values):
    async with db() as session, session.begin():
        user = User(telegram_id=actor)
        session.add(user)
        await session.flush()
        session.add(BrandProfile(user_id=user.id, extra_json=values))


def test_telegram_explicit_competitor_and_ignored_url_use_real_http_composition(mvp_database, monkeypatch):
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        urls = ("https://competitor.example", "https://ignored.example")
        site = analyzer()
        site.analyze.return_value.url_summaries[0].update(url=urls[0], final_url=urls[0])
        api = configured(mvp_database, IntentKind.COMPETITOR_ANALYSIS, analyzer=site, intent_urls=urls)
        app = application(api)
        original_client = httpx.AsyncClient
        requests = []
        async def capture(request):
            requests.append(json.loads(request.content))
        def http_client(**kwargs):
            return original_client(transport=httpx.ASGITransport(app=app), event_hooks={"request": [capture]}, **kwargs)
        monkeypatch.setattr(httpx, "AsyncClient", http_client)
        monkeypatch.setattr(settings, "API_BASE_URL", "http://backend")
        monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
        # Exercise the unmodified client method, authenticated router and service.
        monkeypatch.setattr(flow, "client", CopilotClient())
        try:
            fsm = context(actor)
            msg = message("Проанализируй " + " ".join(urls), actor=actor)
            await flow.receive(msg, fsm)
            await click(fsm, msg, "competitor", "competitor", actor)
            await click(fsm, msg, "skip", "skip", actor)
            assert len(requests) == 1
            assert requests[0]["message"] == msg.text
            assert requests[0]["competitor_urls"] == [urls[0]]
            assert requests[0]["market_source_urls"] == []
            assert "Анализ конкурента" in text_sent(msg)
            assert (await fsm.get_data())["copilot_pending"] is None
            site.analyze.assert_awaited_once_with(urls[0])
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


@pytest.mark.parametrize("kind,request_text,expected", [
    (IntentKind.LEAD_FUNNEL_CALCULATION, "Рассчитай лиды при бюджете 10000 и CPL 500", "Лиды: 20"),
    (IntentKind.POST_GENERATION, "Напиши пост", "Use the supplied product"),
    (IntentKind.CONVERSATION, "Привет", "legacy"),
])
def test_telegram_sync_real_api_never_creates_run(mvp_database, monkeypatch, kind, request_text, expected):
    from bot.handlers import chat
    legacy = AsyncMock()
    monkeypatch.setattr(chat, "_send_to_backend", legacy)
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        api = configured(mvp_database, kind)
        wire(monkeypatch, api)
        await brand(mvp_database, actor, CONTEXT)
        try:
            msg, fsm = message(request_text, actor=actor), context(actor)
            await flow.receive(msg, fsm)
            if expected == "legacy":
                legacy.assert_awaited_once_with(msg, request_text, actor_id=actor)
                assert not msg.answer.called
            else:
                assert expected in text_sent(msg)
            async with mvp_database() as session:
                owner = await session.scalar(select(User.id).where(User.telegram_id == actor))
                assert not (await session.scalars(select(MarketingRun).where(MarketingRun.user_id == owner))).all()
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


@pytest.mark.parametrize("limited", [False, True])
def test_telegram_strategy_duplicate_jobs_worker_status_foreign_owner(mvp_database, monkeypatch, limited):
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        site = analyzer()
        original = site.analyze
        async def analyze(text, *args, **kwargs):
            if limited and "competitor2.example" in text:
                return SimpleNamespace(url_summaries=[{"ok": False, "url": text, "error": "private-provider-detail"}])
            return await original(text, *args, **kwargs)
        site.analyze = analyze
        api = configured(mvp_database, IntentKind.MARKETING_STRATEGY,
            module_model=StrategyModel(use_parents=True), analyzer=site)
        calls = wire(monkeypatch, api)
        await brand(mvp_database, actor, CONTEXT)
        try:
            fsm = context(actor)
            msg = message("Собери стратегию https://competitor1.example https://competitor2.example", actor=actor)
            await flow.receive(msg, fsm)
            await click(fsm, msg, "competitor", "one", actor)
            await click(fsm, msg, "competitor", "two", actor)
            assert "Начал собирать стратегию" in text_sent(msg)
            saved = (await fsm.get_data())["copilot_run"]
            rid = saved["run_id"]
            run, jobs, _ = await graph_state(mvp_database, rid)
            before_ids = {j.job_id for j in jobs}
            assert len(before_ids) == 2
            # Same Telegram update is suppressed locally; backend independently
            # replays the exact HTTP request if delivery is retried by transport.
            await flow.receive(msg, fsm)
            replay = await flow.client.execute(actor, calls[0])
            assert replay.run_id == rid
            assert {j.job_id for j in (await graph_state(mvp_database, rid))[1]} == before_ids
            queued = message(actor=actor)
            await flow.status(queued, actor, rid)
            assert "поставлен в работу" in text_sent(queued)
            for _ in range(12):
                if (await graph_state(mvp_database, rid))[0].status in {"completed", "completed_with_limitations", "blocked", "failed"}:
                    break
                assert await ModuleGraphWorker(api.copilot.graph_service).once()
            result = message(actor=actor)
            cb = SimpleNamespace(data=flow.run_callback(rid), from_user=SimpleNamespace(id=actor), message=result, answer=AsyncMock())
            await check_status(cb)  # Does not need original in-memory FSM.
            text = text_sent(result)
            assert "Стратегический диагноз" in text and "Условия пересмотра" in text and "Эксперименты" in text
            assert ("1 из 2" if limited else "2 из 2") in text
            if limited:
                assert "Анализ одного из конкурентов недоступен" in text
            assert "private-provider-detail" not in text
            foreign = message(actor=actor + 1)
            cb.from_user.id, cb.message = actor + 1, foreign
            await check_status(cb)
            assert text_sent(foreign) == "Результат не найден."
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


def test_telegram_owned_site_confirmation_reacquisition(mvp_database, monkeypatch):
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        page = {"ok": True, "url": OWN, "final_url": OWN, "title": "Acme",
                "main_text_excerpt": "\n".join([PRODUCT, AUDIENCE, JOB, PRICE, LEADER])}
        site = SimpleNamespace(analyze_url=AsyncMock(return_value=SimpleNamespace(url_summaries=[page])))
        extractor = AsyncMock(return_value=extraction())
        api = configured(mvp_database, IntentKind.MARKETING_STRATEGY, owned_analyzer=site, extractor=extractor,
                         module_model=StrategyModel(use_parents=True))
        calls = wire(monkeypatch, api)
        # Require both user scalar clarification and explicit snapshot confirmation.
        await brand(mvp_database, actor, {"business_goal": "Increase bookings"})
        try:
            fsm, msg = context(actor), message(f"Собери стратегию {OWN}", actor=actor)
            await flow.receive(msg, fsm)
            await click(fsm, msg, "own", "own", actor)
            assert "На сайте указано:" in text_sent(msg)
            await click(fsm, msg, "select.0", "select", actor)
            await click(fsm, msg, "confirm", "confirm", actor)
            assert site.analyze_url.await_count == 2
            # Remaining missing alternative is collected under the original key.
            pending = (await fsm.get_data())["copilot_pending"]
            assert pending["fields"] == ["relevant_alternative"]
            answer = message("Spreadsheets", mid=2, actor=actor)
            await flow.receive(answer, fsm)
            assert "Начал собирать стратегию" in text_sent(answer)
            assert len({p.request_key for p in calls}) == 1
            assert calls[-1].confirmation.confirmed is True
            rid = (await fsm.get_data())["copilot_run"]["run_id"]
            for _ in range(3):
                assert await ModuleGraphWorker(api.copilot.graph_service).once()
            result = message(actor=actor)
            await flow.status(result, actor, rid)
            assert "Стратегический диагноз" in text_sent(result) and "Эксперименты" in text_sent(result)
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())
