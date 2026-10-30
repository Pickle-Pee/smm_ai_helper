"""F6/R1: untrusted successful bodies and bounded one-shot action keyboards."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram import Bot, types

from bot import backend
from bot.handlers import chat, workflow
from bot.workflow_contracts import validate_workflow
from tests.test_telegram_copilot import message, patch_http, text_sent
from tests.test_telegram_hardening_flows import callback
from tests.test_telegram_navigation_fixtures import no_selected_project

pytestmark = pytest.mark.usefixtures("no_selected_project")

RID = "ab" * 16


def status():
    return {"run_id": RID, "status": "awaiting_creative", "current_step": "analysis", "error": None,
        "missing_fields": [], "artifacts": {"analysis": {
            "schema_version": "marketing_artifact.v1", "run_id": RID, "step": "analysis",
            "result": {"schema_version": "competitor_analysis.v1", "observed_positioning": "Saved positioning",
                "strengths": ["Clear offer"], "weaknesses": ["Missing price"],
                "customer_hypotheses": ["Compare prices"], "differentiation": ["Publish price"],
                "practical_brief": "Test the offer", "assumptions": [], "limitations": ["One page only"],
                "claims": [{"text": "Test price visibility", "output_name": "observable_positioning",
                    "kind": "HYPOTHESIS", "confidence": "LOW", "evidence_ids": [], "parent_claim_ids": []}]},
            "limitations": ["One page only"], "evidence": [{"source_class": "EXTERNAL_PRIMARY", "provenance": "https://example.com"}],
            "images": []}}, "jobs": [{"job_id": "job", "step": "analysis", "status": "succeeded", "error": None}],
        "delivery": [{"id": "delivery", "status": "delivered", "part": 0}]}


def malformed():
    values = [{}, [], {"status": "completed"}, {"run_id": RID}, {"run_id": RID, "status": "unknown"}]
    for field in ("current_step", "error", "missing_fields", "artifacts", "jobs", "delivery"):
        item = status()
        item.pop(field)
        values.append(item)
    values.append({**status(), "status": "completed", "artifacts": {}})
    for field, value in [("run_id", 12), ("artifacts", []), ("artifacts", {"analysis": {}}),
            ("delivery", [None]), ("delivery", [{"id": "d", "status": "completed", "part": 0}]),
            ("delivery", [{"id": "d", "status": "delivered", "part": "0"}]),
            ("delivery", [{"id": "d", "status": "delivered", "part": True}]),
            ("jobs", [{"job_id": "j", "step": "analysis", "status": "done"}]), ("error", {"secret": "raw"}),
            ("missing_fields", ["unknown"])]:
        values.append({**status(), field: value})
    for field, value in [("result", []), ("result", {}), ("limitations", [3]), ("evidence", [{}]),
            ("images", [{"url": "/images/saved.png"}]),
            ("images", [{"image_id": "saved", "url": 3}]),
            ("images", [{"image_id": "saved", "url": "https://foreign/images/saved.png"}]),
            ("run_id", "cd" * 16), ("step", "creative")]:
        item = status()
        item["artifacts"]["analysis"][field] = value
        values.append(item)
    item = status()
    item["artifacts"]["analysis"]["result"]["strengths"] = [123]
    values.append(item)
    item = status()
    item.update(status="needs_input", missing_fields=[])
    values.append(item)
    return values


@pytest.mark.parametrize("body", malformed())
def test_malformed_success_at_http_and_render_boundaries(monkeypatch, body):
    patch_http(monkeypatch, lambda request: httpx.Response(200, json=body))
    async def check():
        with pytest.raises(backend.BackendError):
            await backend.request("GET", f"/workflows/{RID}", 123)
        # Also protect the render boundary when callers replace/mock HTTP.
        monkeypatch.setattr(backend, "request", AsyncMock(return_value=body))
        msg = message("/analyze https://example.com")
        await workflow.analyze(msg)
        assert "некорректный ответ" in text_sent(msg)
        assert "Все шаги завершены" not in text_sent(msg)
        msg = message(f"/result {RID}")
        await workflow.saved_run(msg)
        assert "Не удалось получить сохранённый результат" in text_sent(msg)
    asyncio.run(check())


def test_valid_artifact_preserves_result_and_keyboard(monkeypatch):
    original = status()
    assert validate_workflow(original) == original
    monkeypatch.setattr(backend, "request", AsyncMock(return_value=original))
    msg = message(f"/result {RID}")
    asyncio.run(workflow.saved_run(msg))
    assert "Saved positioning" in text_sent(msg)
    assert "One page only" in text_sent(msg)
    assert msg.answer.call_args.kwargs["reply_markup"].inline_keyboard[0][0].callback_data == f"mvp:{RID}:creative"


def test_mentor_http_deadline_allows_bounded_serialization_and_generation(monkeypatch):
    clients = patch_http(monkeypatch, lambda request: httpx.Response(200, json={}))
    async def check():
        await backend.request("POST", f"/copilot/runs/{'a' * 64}/mentor/questions", 123, payload={})
        assert clients[-1]["timeout"] == 75
        await backend.request("GET", f"/copilot/runs/{'a' * 64}/mentor/questions", 123)
        assert clients[-1]["timeout"] == 10
    asyncio.run(check())


@pytest.mark.parametrize("body", [{}, [{"run_id": RID}], [{"run_id": RID, "status": []}], [None]])
def test_malformed_run_list_is_controlled(monkeypatch, body):
    monkeypatch.setattr(backend, "request", AsyncMock(return_value=body))
    msg = message("/runs")
    asyncio.run(workflow.runs(msg))
    assert "некорректный список" in text_sent(msg)


@pytest.fixture
def ephemeral(monkeypatch):
    monkeypatch.setattr(chat, "ACTION_STORE", {})
    monkeypatch.setattr(chat, "ACTION_EXPIRES", {})
    clock = SimpleNamespace(now=1000.)
    monkeypatch.setattr(chat.time, "monotonic", lambda: clock.now)
    return clock


def button(actor=123, text="Continue"):
    return chat._actions_keyboard(actor, [{"text": text}]).inline_keyboard[0][0].callback_data


def test_action_store_bounds_users_and_actions(ephemeral):
    first = button(0)
    for actor in range(1, 1500):
        button(actor)
    assert len(chat.ACTION_STORE) == len(chat.ACTION_EXPIRES) == chat.ACTION_MAX_USERS
    assert "0" not in chat.ACTION_STORE
    actions = [{"text": f"Action {i}"} for i in range(100)]
    markup = chat._actions_keyboard(1499, actions)
    assert len(markup.inline_keyboard) == chat.ACTION_MAX_PER_USER
    assert sum(map(len, chat.ACTION_STORE.values())) <= chat.ACTION_MAX_USERS * chat.ACTION_MAX_PER_USER
    assert first.split(":", 1)[1] not in chat.ACTION_STORE.get("0", {})
    assert chat._actions_keyboard(1499, [{"text": "x" * (chat.ACTION_MAX_TEXT_CHARS + 1)}]) is None
    assert "1499" not in chat.ACTION_STORE


def test_expiry_is_absolute_and_does_not_execute_or_revive(ephemeral, monkeypatch):
    backend_call = AsyncMock()
    monkeypatch.setattr(chat, "_send_to_backend", backend_call)
    old = button()
    ephemeral.now += chat.ACTION_TTL_SECONDS
    async def check():
        await chat.on_action(callback(old))
        backend_call.assert_not_awaited()
        assert not chat.ACTION_STORE and not chat.ACTION_EXPIRES
        new = button()
        assert old != new
        await chat.on_action(callback(old))
        backend_call.assert_not_awaited()
        await asyncio.gather(*(chat.on_action(callback(new)) for _ in range(10)))
        backend_call.assert_awaited_once()
        assert not chat.ACTION_STORE and not chat.ACTION_EXPIRES
    asyncio.run(check())


def test_eviction_and_foreign_actor_fail_closed(ephemeral, monkeypatch):
    monkeypatch.setattr(chat, "ACTION_MAX_USERS", 1)
    backend_call = AsyncMock()
    monkeypatch.setattr(chat, "_send_to_backend", backend_call)
    old = button(123)
    current = button(456)
    async def check():
        await chat.on_action(callback(old))
        await chat.on_action(callback(current, actor=123))
        backend_call.assert_not_awaited()
        await chat.on_action(callback(current, actor=456))
        backend_call.assert_awaited_once()
    asyncio.run(check())


def test_real_dispatcher_malformed_success_is_safe(monkeypatch):
    from bot.main import create_dispatcher
    monkeypatch.setattr(Bot, "__call__", AsyncMock(return_value=True))
    monkeypatch.setattr(backend, "request", AsyncMock(return_value={}))
    async def check():
        dp, bot = create_dispatcher(), Bot("123456:offline-token")
        try:
            msg = types.Message(message_id=1, date=datetime.now(timezone.utc),
                chat=types.Chat(id=123, type="private"), from_user=types.User(id=123, is_bot=False, first_name="User"),
                text="/analyze https://example.com")
            await dp.feed_update(bot, types.Update(update_id=1, message=msg))
            assert "некорректный ответ" in Bot.__call__.call_args.args[0].text
        finally:
            await bot.session.close()
            await dp.storage.close()
            await dp.fsm.events_isolation.close()
            for router in dp.sub_routers:
                router._parent_router = None
    asyncio.run(check())
