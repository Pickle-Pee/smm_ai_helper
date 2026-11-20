"""Automatic Telegram delivery of Copilot graph run results.

The graph's terminal transition records one durable ``WorkflowDelivery`` notice
in the same PostgreSQL transaction. The bot's existing delivery poller claims it,
reads the persisted run through the owner-scoped read-only run endpoint and sends
it. Nothing here calls a provider again or depends on the status button, FSM or Redis.
"""
import asyncio
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from sqlalchemy import select, update

from app.config import settings
from app.models import Job, MarketingRun, User, WorkflowDelivery
from app.marketing_copilot.contracts import IntentKind
from app.orchestration_runtime.worker import ModuleGraphWorker
from app.workflows.delivery import DeliveryService
from bot import copilot_contracts as dto, delivery
from bot import copilot_flow as flow
from tests.postgresql_support import mvp_database
from tests.test_graph_postgresql import Clock, cleanup, notices, setup, state

RID = "a" * 64
TERMINAL = {"completed", "completed_with_limitations", "blocked", "failed"}


# --------------------------------------------------------------------------- bot side (no PostgreSQL)

class FakeBot:
    """Fake Telegram transport: records sends, optionally fails on given calls."""

    def __init__(self, failures=None):
        self.sent, self.calls, self.failures = [], 0, dict(failures or {})

    async def send_message(self, chat_id, text, **kwargs):
        self.calls += 1
        failure = self.failures.pop(self.calls, None)
        if failure is not None:
            raise failure
        self.sent.append((chat_id, text, kwargs.get("reply_markup")))
        return SimpleNamespace(message_id=1000 + len(self.sent))

    async def send_photo(self, *args, **kwargs):  # pragma: no cover - not used here
        raise AssertionError("unexpected photo")


SECTION_KEYS = ("strategic_diagnosis", "main_growth_constraint", "strategic_priorities", "trade_offs",
                "resource_priorities", "strategic_bets", "roadmap", "risks", "decision_triggers")


def run_body(run_id=RID, status="COMPLETED"):
    body = {"schema_version": "copilot_api.v1", "run_id": run_id, "status": status}
    if status in {"COMPLETED", "COMPLETED_WITH_LIMITATIONS"}:
        section = {"text": "Текст раздела", "items": ["Пункт"]}
        body["strategy"] = {key: section for key in SECTION_KEYS}
    elif status == "FAILED":
        body["failure"] = {"code": "result_unavailable", "message": "x", "actions": ["y"]}
    parse(body)
    return body


def parse(body):
    return dto.RunResponse.model_validate_json(json.dumps(body))


class Backend:
    """Fake backend for the poller: claim queue, read-only run GET and ack log."""

    def __init__(self, claims, run=None, run_status=200):
        self.claims, self.run, self.run_status = list(claims), run, run_status
        self.acks, self.paths = [], []

    def __call__(self, request):
        self.paths.append((request.method, request.url.path))
        if request.url.path == "/internal/delivery/claim":
            return httpx.Response(200, json=self.claims.pop(0) if self.claims else None)
        if request.url.path.startswith("/copilot/runs/"):
            assert request.method == "GET"
            assert request.headers["x-telegram-user-id"] == "777"
            return httpx.Response(self.run_status, json=self.run if self.run_status == 200 else {"code": "not_found"})
        if request.url.path.endswith("/ack"):
            self.acks.append(json.loads(request.content))
            return httpx.Response(200, json={"accepted": True})
        raise AssertionError(f"unexpected request {request.method} {request.url}")


def claim(payload, token="b" * 32):
    return {"delivery_id": "d" * 32, "claim_token": token, "telegram_id": 777, "payload": payload}


def notice(**extra):
    return {"kind": "copilot_run", "run_id": RID, **extra}


async def poll(bot, backend):
    async with httpx.AsyncClient(transport=httpx.MockTransport(backend)) as client:
        return await delivery.deliver_once(bot, client)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(delivery.settings, "API_BASE_URL", "http://backend")
    monkeypatch.setattr(delivery.settings, "BOT_BACKEND_TOKEN", "api-test")


def test_completed_run_is_sent_without_button_and_without_generation(configured):
    run = parse(run_body())
    expected = flow.run_messages(run, title="Стратегия продвижения — курс")
    backend, bot = Backend([claim(notice(title="Стратегия продвижения — курс"))], run_body()), FakeBot()
    assert asyncio.run(poll(bot, backend))
    assert [text for _, text, _ in bot.sent] == [text for text, _ in expected]
    assert all(chat == 777 for chat, _, _ in bot.sent)
    assert "Запрос: Стратегия продвижения — курс" in bot.sent[0][1]
    # The last message carries the explanation button, as with the status button.
    assert bot.sent[-1][2].inline_keyboard[0][0].callback_data.startswith("cm:")
    assert backend.acks == [{"claim_token": "b" * 32, "message_id": 1000 + len(bot.sent)}]
    # Only claim, one read-only GET and ack: no execute/mentor/provider path.
    assert [m for m, _ in backend.paths] == ["POST", "GET", "POST"]
    assert backend.paths[1][1] == f"/copilot/runs/{RID}"


def test_terminal_failure_is_notified_automatically(configured):
    backend, bot = Backend([claim(notice())], run_body(status="FAILED")), FakeBot()
    asyncio.run(poll(bot, backend))
    text = "\n".join(t for _, t, _ in bot.sent)
    assert "Не удалось завершить запрос" in text and RID in text
    assert "message_id" in backend.acks[0]


def test_partial_send_resumes_after_confirmed_messages(configured):
    run = parse(run_body())
    total = len(flow.run_messages(run))
    assert total >= 3
    retry = TelegramRetryAfter(method=SendMessage(chat_id=777, text="x"), message="flood", retry_after=7)
    bot = FakeBot({2: retry})
    first = Backend([claim(notice())], run_body())
    asyncio.run(poll(bot, first))
    assert first.acks == [{"claim_token": "b" * 32, "sent_parts": 1, "retryable": True, "retry_after": 7}]
    # Backend stores progress; the next claim resumes after the confirmed message.
    second = Backend([claim(notice(sent_parts=1), token="c" * 32)], run_body())
    asyncio.run(poll(bot, second))
    texts = [t for _, t, _ in bot.sent]
    assert texts == [t for t, _ in flow.run_messages(run)]  # each message exactly once
    assert "message_id" in second.acks[0] and "sent_parts" not in second.acks[0]


@pytest.mark.parametrize("case,ack", [
    ("not_ready", {"retryable": True, "retry_after": 30}),
    ("missing", {"retryable": False}),
    ("foreign_run", {"retryable": False}),
    ("blocked_user", {"retryable": False, "sent_parts": 0}),
    ("backend_down", {"retryable": True}),
])
def test_failure_outcomes_are_explicit_and_bounded(configured, case, ack):
    run, status = run_body(), 200
    bot = FakeBot()
    if case == "not_ready":
        run = run_body(status="RUNNING")
    elif case == "missing":
        status = 404
    elif case == "foreign_run":
        run = run_body(run_id="f" * 64)
    elif case == "blocked_user":
        bot = FakeBot({1: TelegramForbiddenError(method=SendMessage(chat_id=777, text="x"), message="blocked")})
    elif case == "backend_down":
        status = 503
    backend = Backend([claim(notice())], run, status)
    asyncio.run(poll(bot, backend))
    assert backend.acks == [{"claim_token": "b" * 32, **ack}]
    assert bot.sent == []


@pytest.mark.parametrize("bad", [None, "", "../x", "A" * 64, 5])
def test_invalid_notice_identity_fails_closed_before_any_read(configured, bad):
    backend, bot = Backend([claim({"kind": "copilot_run", "run_id": bad})], run_body()), FakeBot()
    asyncio.run(poll(bot, backend))
    assert backend.acks == [{"claim_token": "b" * 32, "retryable": False}]
    assert [p for _, p in backend.paths if p.startswith("/copilot")] == []


def test_status_button_and_delivery_render_identically():
    run = parse(run_body())
    msg = SimpleNamespace(answer=AsyncMock())
    original = flow.client
    flow.client = SimpleNamespace(run=AsyncMock(return_value=run))
    try:
        asyncio.run(flow.status(msg, 777, RID))
    finally:
        flow.client = original
    assert [c.args[0] for c in msg.answer.call_args_list] == [t for t, _ in flow.run_messages(run)]


def test_started_message_promises_automatic_delivery():
    import inspect
    source = inspect.getsource(flow.execute)
    assert "Результат пришлю сюда автоматически" in source


# --------------------------------------------------------------------------- backend side (PostgreSQL)

def test_terminal_notice_claim_isolation_progress_and_bounded_attempts(mvp_database):
    async def exercise():
        service, clock, rid, owner = await setup(mvp_database)
        try:
            from tests.graph_fakes import FakeModel, registry
            from app.orchestration_runtime.service import GraphExecutionService
            worker = ModuleGraphWorker(GraphExecutionService(mvp_database, executors=registry(FakeModel(use_parents=True)), clock=clock))
            assert await worker.once()
            assert await notices(mvp_database, rid) == []  # not terminal yet: nothing to deliver
            # Simulated worker restart: a fresh service instance finishes the run.
            worker = ModuleGraphWorker(GraphExecutionService(mvp_database, executors=registry(FakeModel(use_parents=True)), clock=clock))
            assert await worker.once()
            run, _, _ = await state(mvp_database, rid)
            assert run.status == "completed"
            [row] = await notices(mvp_database, rid)
            async with mvp_database() as session:
                actor = await session.scalar(select(User.telegram_id).where(User.id == owner))
                # Isolate from leftovers of other tests sharing the disposable database.
                await session.execute(update(WorkflowDelivery).where(WorkflowDelivery.delivery_id != row.delivery_id,
                    WorkflowDelivery.status.in_(["pending", "sending"])).values(status="failed", claim_token=None, lease_until=None))
                await session.commit()
            deliveries = DeliveryService(mvp_database, clock=clock)
            first, second = await asyncio.gather(deliveries.claim(), deliveries.claim())
            claimed = [c for c in (first, second) if c is not None]
            assert len(claimed) == 1  # concurrent pollers: one lease winner
            item = claimed[0]
            assert item["telegram_id"] == actor  # resolved from the run owner only
            assert item["payload"]["run_id"] == rid
            assert await deliveries.acknowledge(item["delivery_id"], item["claim_token"], retryable=True, sent_parts=2)
            clock.tick(600)
            again = await deliveries.claim()
            assert again["payload"]["sent_parts"] == 2
            # Progress never moves backwards and a stale token is fenced.
            assert not await deliveries.acknowledge(item["delivery_id"], item["claim_token"], message_id=5)
            assert await deliveries.acknowledge(again["delivery_id"], again["claim_token"], retryable=True, sent_parts=1)
            clock.tick(600)
            third = await deliveries.claim()
            assert third["payload"]["sent_parts"] == 2
            assert await deliveries.acknowledge(third["delivery_id"], third["claim_token"], message_id=42)
            async with mvp_database() as session:
                stored = await session.get(WorkflowDelivery, row.delivery_id)
                assert stored.status == "delivered" and stored.telegram_message_id == 42
            clock.tick(600)
            assert await deliveries.claim() is None  # delivered once; nothing re-sent
            # Attempts are bounded: a permanently failing notice stops at the limit.
            async with mvp_database() as session, session.begin():
                stored = await session.get(WorkflowDelivery, row.delivery_id)
                stored.status, stored.telegram_message_id = "pending", None
            for _ in range(10):
                clock.tick(3600)
                current = await deliveries.claim()
                if current is None:
                    break
                await deliveries.acknowledge(current["delivery_id"], current["claim_token"], retryable=True)
            async with mvp_database() as session:
                stored = await session.get(WorkflowDelivery, row.delivery_id)
                assert stored.status == "failed" and stored.attempts == 8
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


# --------------------------------------------------------------------------- end to end

@pytest.mark.parametrize("experiments_enabled", [True, False], ids=["experiments", "ai_core_1_0_release"])
def test_telegram_request_result_arrives_without_pressing_status(mvp_database, monkeypatch, experiments_enabled):
    """Telegram -> API -> PostgreSQL -> graph worker -> notice -> poller -> fake Telegram.

    The ai_core_1_0_release case uses the release configuration COPILOT_EXPERIMENTS_ENABLED=false:
    the graph has no EXPERIMENTS node, no EXPERIMENTS request reaches the model, and the
    automatically delivered result carries the temporary-limitation notice.
    """
    monkeypatch.setattr(settings, "COPILOT_EXPERIMENTS_ENABLED", experiments_enabled)
    from fastapi import FastAPI
    from app.routers import workflows
    from app.routers.copilot import router as copilot_router
    from tests.test_copilot_api_postgresql import configured as configured_api, remove_actor
    from tests.test_module_executors import analyzer
    from tests.test_strategy_builder import StrategyModel
    from tests.test_telegram_copilot import message, context, click, text_sent
    from tests.test_telegram_copilot_postgresql import brand, wire, CONTEXT

    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        other = actor + 1
        model = StrategyModel(use_parents=True)
        api = configured_api(mvp_database, IntentKind.MARKETING_STRATEGY, module_model=model, analyzer=analyzer())
        app = FastAPI()
        app.include_router(copilot_router)
        app.include_router(workflows.delivery_router)
        app.state.copilot_api = api
        monkeypatch.setattr(workflows, "delivery", DeliveryService(mvp_database))
        wire(monkeypatch, api, app=app)
        await brand(mvp_database, actor, CONTEXT)
        try:
            fsm = context(actor)
            msg = message("Собери стратегию https://competitor1.example", actor=actor)
            await flow.receive(msg, fsm)
            await click(fsm, msg, "competitor", "one", actor)
            assert "Результат пришлю сюда автоматически" in text_sent(msg)
            rid = (await fsm.get_data())["copilot_run"]["run_id"]
            # The user leaves: FSM is gone (bot restart), nobody presses a button.
            await fsm.clear()
            for _ in range(12):
                if (await state(mvp_database, rid))[0].status in TERMINAL:
                    break
                assert await ModuleGraphWorker(api.copilot.graph_service).once()
            run, jobs, _ = await state(mvp_database, rid)
            assert run.status in {"completed", "completed_with_limitations"}
            steps = {job.workflow_step for job in jobs}
            asked_experiments = [c for c in model.calls if "experiments_support_selection_catalog" in c["text"]
                                 or "evidence_basis" in json.loads(c["text"]).get("expected_outputs", [])]
            assert ("experiments" in steps) is experiments_enabled
            assert bool(asked_experiments) is experiments_enabled
            assert ({"code": "experiments_disabled"} in run.state_json["limitations"]) is not experiments_enabled
            model_calls = len(model.calls)
            async with mvp_database() as session, session.begin():
                # Isolate from leftovers of other tests sharing the disposable database.
                mine = (await notices(mvp_database, rid))[0].delivery_id
                await session.execute(update(WorkflowDelivery).where(WorkflowDelivery.delivery_id != mine,
                    WorkflowDelivery.status.in_(["pending", "sending"])).values(status="failed", claim_token=None, lease_until=None))
            bot = FakeBot()
            # A freshly started poller (bot restart) finds the durable notice.
            async with httpx.AsyncClient() as client:
                while await delivery.deliver_once(bot, client):
                    pass
            assert bot.sent and {chat for chat, _, _ in bot.sent} == {actor}
            text = "\n".join(t for _, t, _ in bot.sent)
            assert "Стратегия готова" in text and "Стратегический диагноз" in text
            assert ("План экспериментов временно не формируется" in text) is not experiments_enabled
            assert len(model.calls) == model_calls  # delivery never generates
            [row] = await notices(mvp_database, rid)
            assert row.status == "delivered" and row.attempts == 1
            # Pressing the status button afterwards still reads the same saved result.
            later = message(actor=actor)
            await flow.status(later, actor, rid)
            assert "Стратегический диагноз" in text_sent(later)
            assert len(model.calls) == model_calls
            # Another user can neither read nor receive this run.
            foreign = message(actor=other)
            await flow.status(foreign, other, rid)
            assert text_sent(foreign) == "Результат не найден."
        finally:
            await remove_actor(mvp_database, actor)
    asyncio.run(check())


def test_web_only_owner_gets_no_telegram_notice(mvp_database):
    """B1a: a web-only owner (users.telegram_id IS NULL) has no Telegram chat to notify.

    The run still finishes normally; no WorkflowDelivery row is created, so the poller
    can never send it to some other chat. A web delivery channel arrives with B5/B6.
    """
    from app.orchestration_runtime.service import GraphExecutionService
    from tests.graph_fakes import FakeModel, compiled, registry

    async def exercise():
        executors = registry(FakeModel(use_parents=True))
        service = GraphExecutionService(mvp_database, executors=executors, clock=Clock())
        rid = uuid.uuid4().hex
        async with mvp_database() as session, session.begin():
            user = User()
            session.add(user)
            await session.flush()
            owner = user.id
        assert user.telegram_id is None
        await service.start_compiled_run(owner_id=owner, run_id=rid, plan=compiled(executors))
        try:
            for _ in range(6):
                run, jobs, _ = await state(mvp_database, rid)
                if run.status in TERMINAL:
                    break
                for job in jobs:
                    if job.status.value == "pending":
                        assert await ModuleGraphWorker(service).once(job.job_id)
            run, _, artifacts = await state(mvp_database, rid)
            assert run.status == "completed" and len(artifacts) == 2
            assert await notices(mvp_database, rid) == []
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())
