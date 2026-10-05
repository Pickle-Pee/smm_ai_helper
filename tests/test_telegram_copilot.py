"""Telegram -> typed HTTP adapter regressions; Telegram/providers are offline."""
import asyncio
import ast
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from pydantic import TypeAdapter

from app.config import settings
from bot import copilot_contracts as dto, copilot_flow as flow, copilot_rendering as render
from bot.copilot_client import CopilotClient, CopilotError
from bot.handlers.copilot import check_status

RID = "ab" * 32


def message(text="Собери стратегию", mid=1, actor=123):
    return SimpleNamespace(text=text, message_id=mid, from_user=SimpleNamespace(id=actor),
        chat=SimpleNamespace(id=actor, type="private"), entities=[], answer=AsyncMock(), edit_reply_markup=AsyncMock())


def context(actor=123):
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=actor, user_id=actor))


async def click(state, msg, name, cid="click", actor=123):
    pending = (await state.get_data())["copilot_pending"]
    callback = SimpleNamespace(data=flow.action(pending, name), id=cid, from_user=SimpleNamespace(id=actor),
                               message=msg, answer=AsyncMock())
    await flow.callback_action(callback, state)
    return callback


def text_sent(msg):
    return "\n".join(c.args[0] for c in msg.answer.call_args_list)


def started():
    return dto.StartedResponse(run_id=RID, status_url=f"/copilot/runs/{RID}")


def owned(snapshot="snapshot.first", statement="statement.first"):
    return dto.OwnedSiteResult(outcome="ACQUIRED", snapshot_id=snapshot, candidates=[
        dto.ConfirmationCandidate(statement_id=statement, field="stated_product_service",
            statement="<b>Напоминания</b> [ссылка](bad)", source_url="https://own.example/?a=<b>&x=1")])


def patch_http(monkeypatch, responder):
    original = httpx.AsyncClient
    captures = []
    def factory(**kwargs):
        captures.append(kwargs)
        return original(transport=httpx.MockTransport(responder), **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", factory)
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "test-secret")
    monkeypatch.setattr(settings, "API_BASE_URL", "http://backend")
    return captures


def test_public_client_contract_matches_backend_schema():
    from app.marketing_copilot import api_contracts as server
    for name in ("ExecuteRequest", "ExecuteResponse", "RunResponse", "RunListResponse", "ErrorResponse"):
        assert TypeAdapter(getattr(dto, name)).json_schema() == TypeAdapter(getattr(server, name)).json_schema()


def test_bot_imports_http_contract_only():
    forbidden = ("app.marketing_copilot", "app.module_execution", "app.orchestration_runtime",
                 "app.module_registry", "app.models", "app.database", "app.db", "sqlalchemy", "redis")
    for path in Path("bot").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            imports = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            assert not any(value.startswith(forbidden) for value in imports), path
    # Catch transitive imports, not just source-level spelling.
    script = "import bot.main, sys; assert not any(k.startswith(" + repr(forbidden) + ") for k in sys.modules)"
    subprocess.run([sys.executable, "-c", script], check=True, capture_output=True)


@pytest.mark.parametrize("status,category", [(401, "auth"), (403, "auth"), (404, "not_found"),
    (422, "invalid_state"), (503, "temporary"), (500, "server"), (502, "server"), (409, "server")])
def test_http_errors_hide_body(monkeypatch, caplog, status, category):
    patch_http(monkeypatch, lambda _: httpx.Response(status, text="private-body-secret"))
    with pytest.raises(CopilotError) as exc:
        asyncio.run(CopilotClient().execute(123, dto.ExecuteRequest(request_key="k", message="private-message")))
    assert exc.value.category == category
    assert "private-body-secret" not in str(exc.value) + caplog.text
    assert "private-message" not in caplog.text and "test-secret" not in caplog.text


@pytest.mark.parametrize("category", ["request_conflict", "confirmation_changed"])
def test_http_conflict_decoding(monkeypatch, category):
    patch_http(monkeypatch, lambda _: httpx.Response(409, json=dto.ErrorResponse(code=category, owned_site=owned()).model_dump(mode="json")))
    with pytest.raises(CopilotError) as exc:
        asyncio.run(CopilotClient().execute(123, dto.ExecuteRequest(request_key="k", message="text")))
    assert exc.value.category == category and exc.value.owned_site.snapshot_id == "snapshot.first"


@pytest.mark.parametrize("failure", ["network", "json", "schema", "wrong_run"])
def test_http_network_and_malformed_response(monkeypatch, failure):
    def respond(request):
        if failure == "network":
            raise httpx.ConnectError("private-host", request=request)
        if failure == "json":
            return httpx.Response(200, text="not-json")
        return httpx.Response(200, json={"run_id": "cd" * 32, "status": "COMPLETED"} if failure == "wrong_run" else {})
    patch_http(monkeypatch, respond)
    with pytest.raises(CopilotError) as exc:
        asyncio.run(CopilotClient().run(123, RID))
    assert exc.value.category == ("unavailable" if failure == "network" else "invalid_response")


def test_direct_http_routing_auth_rendering_and_duplicate(monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=dto.DirectResponse(calculation=dto.Calculation(calculation_type="leads",
            formula="budget/cpl", inputs=dto.CalculationInputs(budget="10000", cpl="500"),
            outputs=dto.CalculationOutputs(leads="20"), assumptions=["Все суммы в рублях."])).model_dump(mode="json"))
    configurations = patch_http(monkeypatch, respond)
    async def check():
        state, msg = context(), message("Рассчитай лиды при бюджете 10000 и CPL 500")
        await flow.receive(msg, state)
        await flow.receive(msg, state)
        assert len(calls) == 1
        assert calls[0].url.path == "/copilot/execute"
        assert calls[0].headers["authorization"] == "Bearer test-secret"
        assert calls[0].headers["x-telegram-user-id"] == "123"
        assert json.loads(calls[0].content)["request_key"] == "tg:123:123:1"
        assert "Лиды: 20" in text_sent(msg) and "Бюджет делим" in text_sent(msg)
        assert "Допущения" in text_sent(msg)
        assert all(c.kwargs["parse_mode"] is None for c in msg.answer.call_args_list)
        assert (await state.get_data()).get("copilot_run") is None
        assert configurations[0]["timeout"].connect == 10
        await flow.receive(message(mid=2), state)
        assert json.loads(calls[1].content)["request_key"] != "tg:123:123:1"
    asyncio.run(check())


def test_post_and_conversation_are_single_results(monkeypatch):
    from bot.handlers import chat
    legacy = AsyncMock()
    monkeypatch.setattr(chat, "_send_to_backend", legacy)
    api = SimpleNamespace(execute=AsyncMock(side_effect=[dto.ModuleResponse(result=dto.Post(
        headline="Заголовок", body="Текст", cta="Попробуйте", limitations=["Нужна проверка"])), dto.ConversationResponse()]))
    monkeypatch.setattr(flow, "client", api)
    async def check():
        state, msg = context(), message("Напиши пост")
        await flow.receive(msg, state)
        assert "Заголовок\nТекст\nПризыв" in text_sent(msg)
        assert "Ограничения" in text_sent(msg)
        assert not legacy.called and "copilot_run" not in await state.get_data()
        other = message("Привет", mid=2)
        await flow.receive(other, state)
        legacy.assert_awaited_once_with(other, "Привет", actor_id=123)
        other.answer.assert_not_called()
    asyncio.run(check())


def test_grouped_clarification_accumulates_context_same_key(monkeypatch):
    api = SimpleNamespace(execute=AsyncMock(side_effect=[dto.NeedsInputResponse(code="missing",
        alternatives=[["product_truth", "relevant_alternative"]]), started()]))
    monkeypatch.setattr(flow, "client", api)
    async def check():
        state, msg = context(), message()
        await flow.receive(msg, state)
        assert "свойства продукта" in text_sent(msg) and "Чем клиент" in text_sent(msg)
        assert "product_truth" not in text_sent(msg)
        await flow.receive(msg, state)  # Original redelivery is not a clarification answer.
        answer = message("Напоминания", mid=2)
        await flow.receive(answer, state)
        await flow.receive(answer, state)  # Duplicate answer must not fill the next field.
        assert api.execute.await_count == 1
        await flow.receive(message("Таблицы", mid=3), state)
        first, second = [call.args[1] for call in api.execute.call_args_list]
        assert first.request_key == second.request_key
        assert second.message == msg.text
        assert second.context.product_truth == "Напоминания" and second.context.relevant_alternative == "Таблицы"
        data = await state.get_data()
        assert data["copilot_pending"] is None and "status" not in data["copilot_run"]
        assert data["copilot_run"]["run_id"] == RID
    asyncio.run(check())


def test_url_roles_are_explicit_bounded_and_stale_buttons_rejected(monkeypatch):
    api = SimpleNamespace(execute=AsyncMock(return_value=started()))
    monkeypatch.setattr(flow, "client", api)
    async def check():
        state = context()
        msg = message("Стратегия https://own.example https://one.example https://two.example https://three.example https://four.example https://market.example")
        await flow.receive(msg, state)
        api.execute.assert_not_called()
        old = await click(state, msg, "own", "1")
        await flow.callback_action(old, state)
        assert "устарело" in old.answer.call_args.args[0]
        for n in range(3):
            await click(state, msg, "competitor", str(n + 2))
        await click(state, msg, "competitor", "5")
        assert "максимум 3" in text_sent(msg)
        assert len((await state.get_data())["copilot_pending"]["payload"]["competitor_urls"]) == 3
        await click(state, msg, "skip", "6")
        await click(state, msg, "market", "7")
        payload = api.execute.call_args.args[1]
        assert payload.owned_site_url == "https://own.example"
        assert payload.competitor_urls == ["https://one.example", "https://two.example", "https://three.example"]
        assert payload.market_source_urls == ["https://market.example"]
        assert "https://four.example" not in payload.competitor_urls
    asyncio.run(check())


def test_confirmation_all_current_candidates_changed_snapshot_and_replay(monkeypatch):
    api = SimpleNamespace(execute=AsyncMock(side_effect=[dto.NeedsInputResponse(code="missing",
        alternatives=[["product_truth"]], owned_site=owned()),
        CopilotError("confirmation_changed", owned_site=owned("snapshot.new", "statement.new")), started()]))
    monkeypatch.setattr(flow, "client", api)
    async def check():
        state, msg = context(), message("Стратегия https://own.example")
        await flow.receive(msg, state)
        await click(state, msg, "own", "1")
        assert "Нашёл сведения о вашем бизнесе:" in text_sent(msg)
        old = await click(state, msg, "confirm", "2")
        assert "повторное извлечение" in text_sent(msg)
        pending = (await state.get_data())["copilot_pending"]
        assert pending["displayed_statement_ids"] == ["statement.new"]
        assert "confirmation" not in pending["payload"]
        await flow.callback_action(old, state)
        assert "устарело" in old.answer.call_args.args[0]
        old.id = "different-delivery"
        await flow.callback_action(old, state)
        assert api.execute.await_count == 2  # Old token cannot confirm the replacement snapshot.
        await click(state, msg, "confirm", "3")
        values = [c.args[1] for c in api.execute.call_args_list]
        assert len({v.request_key for v in values}) == 1
        assert values[1].confirmation.statement_ids == ["statement.first"]
        assert values[2].confirmation.statement_ids == ["statement.new"]
        assert values[2].confirmation.confirmed is True
        assert len(values[2].confirmation.reference) < 300
    asyncio.run(check())


@pytest.mark.parametrize("category", ["temporary", "unavailable", "server", "request_conflict", "auth", "invalid_state"])
def test_retry_conflict_and_new_request_semantics(monkeypatch, category):
    api = SimpleNamespace(execute=AsyncMock(side_effect=[CopilotError(category), started()]))
    monkeypatch.setattr(flow, "client", api)
    async def check():
        state, msg = context(), message()
        await flow.receive(msg, state)
        if category in {"temporary", "unavailable", "server"}:
            await click(state, msg, "retry")
            assert api.execute.call_args_list[0].args[1] == api.execute.call_args_list[1].args[1]
        else:
            await click(state, msg, "retry")
            assert api.execute.await_count == 1
            await click(state, msg, "new", "new")
            await flow.receive(message(mid=2), state)
            assert api.execute.call_args_list[0].args[1].request_key != api.execute.call_args_list[1].args[1].request_key
    asyncio.run(check())


def test_status_button_survives_lost_fsm_and_checks_clicking_actor(monkeypatch):
    api = SimpleNamespace(run=AsyncMock(side_effect=CopilotError("not_found")))
    monkeypatch.setattr(flow, "client", api)
    callback = SimpleNamespace(data=flow.run_callback(RID), from_user=SimpleNamespace(id=456),
        message=message(actor=999), answer=AsyncMock())
    asyncio.run(check_status(callback))
    api.run.assert_awaited_once_with(456, RID)
    assert text_sent(callback.message) == "Результат не найден."
    assert len(callback.data.encode()) <= 64
    assert flow.decode_run(callback.data) == RID


@pytest.mark.parametrize("value", ["cs:../../../etc", "cs:" + "a" * 64, "cs:", "cs:" + "/" * 43])
def test_malformed_status_callbacks(value):
    with pytest.raises(ValueError):
        flow.decode_run(value)


@pytest.mark.parametrize("status,text", [("QUEUED", "Запрос поставлен"), ("RUNNING", "Стратегия собирается"),
    ("FAILED", "Не удалось завершить"), ("BLOCKED", "Нужно уточнить"), ("COMPLETED", "Результат готов"),
    ("COMPLETED_WITH_LIMITATIONS", "Ограничения")])
def test_every_status_has_safe_presentation(status, text):
    result = dto.RunResponse.model_validate_json(json.dumps({"run_id": RID, "status": status}))
    assert text in "\n".join(render.run(result))


PUBLIC_FAILURES = {
    "result_unavailable": {
        "message": "The request could not be completed.",
        "actions": ["Contact support with the run ID or submit a new request key."],
    },
    "context_required": {
        "message": "Additional context or an accessible source is required.",
        "actions": ["Review the supplied context and sources, then submit a new request key."],
    },
}


def recovery_response(status, code, *, alternate=False):
    failure = None if code is None else {
        "code": code,
        **({"message": "Alternative public wording.", "actions": ["Alternative public recovery action."]}
           if alternate else PUBLIC_FAILURES[code]),
    }
    return dto.RunResponse.model_validate_json(json.dumps({"run_id": RID, "status": status, "failure": failure}))


@pytest.mark.parametrize("status,code", [
    ("FAILED", "result_unavailable"), ("FAILED", None), ("FAILED", "context_required"),
    ("BLOCKED", "context_required"), ("BLOCKED", None), ("BLOCKED", "result_unavailable"),
])
def test_workflow_recovery_state_matrix_is_safe_and_status_specific(status, code):
    sections = render.run(recovery_response(status, code))
    text = "\n".join(sections)
    assert "/new" in text
    if status == "FAILED":
        assert "Не удалось завершить запрос." in text
        assert "Нужно уточнить" not in text and "дополнительные сведения" not in text
    else:
        assert "Нужно уточнить запрос." in text
        assert "Не удалось завершить" not in text
    if status == "FAILED" and code == "result_unavailable":
        assert "Начните новый запрос: /new" in sections
        assert sections[-1] == f"Если ошибка повторяется, передайте поддержке ID запуска:\n{RID}"
        assert text.count(RID) == 1
    else:
        assert RID not in text and "поддержке" not in text
    if status == "BLOCKED" and code == "context_required":
        assert "Нужны дополнительные сведения или доступный источник." in text
        assert "Проверьте сведения и источники" in text
    elif status == "BLOCKED":
        assert "дополнительные сведения" not in text
    for values in PUBLIC_FAILURES.values():
        assert values["message"] not in text
        assert all(action not in text for action in values["actions"])
    assert all(term not in text.lower() for term in (
        "request key", "job_id", "execution_id", "executor", "node_id", "traceback", "provider", "database",
        "context_required", "result_unavailable", "<b>", "`", "[run]",
    ))


@pytest.mark.parametrize("status,code", [("FAILED", "result_unavailable"), ("BLOCKED", "context_required")])
def test_workflow_recovery_depends_on_code_not_public_wording(status, code):
    canonical = render.run(recovery_response(status, code))
    alternative = render.run(recovery_response(status, code, alternate=True))
    assert alternative == canonical
    assert "Alternative public" not in "\n".join(alternative)


def test_failed_and_blocked_recovery_remain_distinct():
    assert render.run(recovery_response("FAILED", "result_unavailable")) != render.run(
        recovery_response("BLOCKED", "context_required"))


@pytest.mark.parametrize("status,code", [("FAILED", "result_unavailable"), ("BLOCKED", "context_required")])
def test_workflow_recovery_status_handler_sends_plain_text(monkeypatch, status, code):
    result = recovery_response(status, code)
    api = SimpleNamespace(run=AsyncMock(return_value=result))
    monkeypatch.setattr(flow, "client", api)
    callback = SimpleNamespace(data=flow.run_callback(RID), from_user=SimpleNamespace(id=123),
        message=message(), answer=AsyncMock())
    asyncio.run(check_status(callback))
    assert [call.args[0] for call in callback.message.answer.call_args_list] == render.run(result)
    assert all(call.kwargs["parse_mode"] is None for call in callback.message.answer.call_args_list)


CREATOR_LIMITATION = (
    "Text post and creative hypotheses only; no image/video generation, "
    "platform-current compliance or performance validation."
)
CREATOR_LIMITATION_RU = (
    "Доступны только текстовый пост и креативные гипотезы; генерация изображений и видео, "
    "проверка актуальных требований платформ и оценка эффективности не выполняются."
)


@pytest.mark.parametrize("limitations,expected", [
    ([CREATOR_LIMITATION], [CREATOR_LIMITATION_RU]),
    (["Unknown provider-specific limitation."], ["Unknown provider-specific limitation."]),
    (["Недостаточно данных"], ["Недостаточно данных"]),
    ([CREATOR_LIMITATION, "Недостаточно данных"], [CREATOR_LIMITATION_RU, "Недостаточно данных"]),
    (["Text post and creative hypotheses only; custom limitation."],
     ["Text post and creative hypotheses only; custom limitation."]),
    ([CREATOR_LIMITATION, CREATOR_LIMITATION], [CREATOR_LIMITATION_RU]),
    (["<b>text</b> [text](https://example.com) * _ #"],
     ["<b>text</b> [text](https://example.com) * _ #"]),
])
def test_creator_post_limitations_use_exact_translation_and_preserve_unknown(limitations, expected):
    post = dto.Post(headline="Заголовок поста", body="Текст поста", cta="Попробуйте", limitations=limitations)
    sections = render.module(post)
    assert sections == [post.headline, post.body, "Призыв к действию\n" + post.cta,
                        "⚠ Ограничения\n" + "\n".join("• " + value for value in expected)]
    if CREATOR_LIMITATION in limitations:
        assert CREATOR_LIMITATION not in "\n".join(sections)


def test_creator_limitation_source_matches_telegram_translation_contract():
    from app.module_execution.executors.creator import CreatorExecutor

    assert CreatorExecutor.limitation == CREATOR_LIMITATION
    assert render.human(CreatorExecutor.limitation) == CREATOR_LIMITATION_RU


def test_strategy_nine_sections_experiments_coverage_and_long_markup_safe():
    from bot.rendering import split_text
    strategy = dto.Strategy(**{key: dto.StrategySection(text="<b>🙂 & [text](url)\n" * 190, items=["Действие"]) for key in render.SECTIONS})
    result = dto.RunResponse(run_id=RID, status=dto.RunStatus.COMPLETED_WITH_LIMITATIONS, strategy=strategy,
        experiments=dto.Experiments(designs=[dto.Experiment(hypothesis="Тест", target_metric="Заявки", intervention="CTA",
            expected_signal="Рост", failure_condition="Без роста", minimum_required_inputs=["Трафик"], time_resource_constraints=["Неделя"])]),
        evidence_coverage=dto.Coverage(competitors_supplied=3, competitors_accepted=2,
            limitations=["One competitor analysis is unavailable.", "Market research was not supplied."]),
        limitations=["Economics are unavailable; profitability and affordability remain unknown."])
    sections = render.run(result)
    text = "\n".join(sections)
    assert all(title in text for title in render.SECTIONS.values())
    assert text.index("Эксперименты") > text.index("Условия пересмотра")
    assert "2 из 3" in text and "одного из конкурентов" in text and "Данных об экономике нет" in text
    for section in sections:
        chunks = split_text(section)
        assert "".join(chunks) == section
        assert all(len(c.encode("utf-16-le")) // 2 <= 3500 for c in chunks)


@pytest.mark.parametrize("kind", ["competitor_analysis", "market_analysis", "positioning"])
def test_findings_hide_keys_and_render_sources(kind):
    result = dto.Findings(kind=kind, findings=[dto.Finding(topic="direct_competitors", text="Наблюдение", kind="INFERENCE", confidence="LOW")],
        sources=[dto.SourceSummary(label="Источник", url="https://example.com/?q=<b>&x=1")], limitations=["Недостаточно данных"])
    text = "\n".join(render.module(result))
    assert "Прямые конкуренты" in text and "низкая уверенность" in text and "Источники" in text and "Ограничения" in text
    assert "LOW" not in text and "direct_competitors" not in text


def test_cancel_before_and_after_run(monkeypatch):
    api = SimpleNamespace(execute=AsyncMock(side_effect=[dto.NeedsInputResponse(code="missing", alternatives=[["product"]]), started()]))
    monkeypatch.setattr(flow, "client", api)
    async def check():
        state, msg = context(), message()
        await flow.receive(msg, state)
        await flow.reset(msg, state, cancel=True)
        assert (await state.get_data())["copilot_pending"] is None
        await flow.receive(message(mid=2), state)
        await flow.reset(msg, state, cancel=True)
        assert "нельзя отменить" in text_sent(msg)
        assert (await state.get_data())["copilot_run"]["run_id"] == RID
    asyncio.run(check())


def test_conversation_delegates_through_existing_chat_http(monkeypatch):
    from app.services.chat_response_service import ChatResponseService
    from bot.handlers import chat
    raw_reply = "**Продвижение:**\nПомогу выбрать каналы.\n\n**Реклама:**\nПомогу проверить гипотезы."
    expected_reply = "Продвижение:\nПомогу выбрать каналы.\n\nРеклама:\nПомогу проверить гипотезы."
    backend_payload = ChatResponseService.normalize({
        "reply": raw_reply, "follow_up_question": "**Продолжить**?",
        "actions": [{"type": "suggestion", "text": "**Проверить** `CPL`"}],
    })
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.path == "/copilot/execute":
            return httpx.Response(200, json={"kind": "CONVERSATION", "delegate": "legacy_chat"})
        assert request.url.path == "/chat/message"
        assert json.loads(request.content)["user_id"] == "tg:123"
        assert request.headers["x-telegram-user-id"] == "123"
        return httpx.Response(200, json={**backend_payload, "images": []})
    patch_http(monkeypatch, respond)
    monkeypatch.setattr(chat, "_chat_action_indicator", AsyncMock())
    monkeypatch.setattr(chat, "_long_request_indicator", AsyncMock())
    async def check():
        msg, fsm = message("Привет"), context()
        msg.answer.return_value = SimpleNamespace(edit_text=AsyncMock(), delete=AsyncMock())
        await flow.receive(msg, fsm)
        assert [c.url.path for c in calls] == ["/copilot/execute", "/chat/message"]
        assert text_sent(msg).count(expected_reply) == 1
        delivered = [c for c in msg.answer.call_args_list if c.args[0] in (expected_reply, "Продолжить?")]
        assert len(delivered) == 2
        assert all(c.kwargs["parse_mode"] is None for c in delivered)
        assert "**" not in text_sent(msg)
        keyboard = delivered[0].kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].text == "Проверить CPL"
    asyncio.run(check())


def test_real_dispatcher_routing_isolation_explicit_features_and_restart(monkeypatch):
    from datetime import datetime, timezone
    from aiogram import Bot, types
    from bot.main import create_dispatcher
    from bot.handlers import workflow, agent_flow, history
    api = SimpleNamespace(execute=AsyncMock(return_value=started()))
    monkeypatch.setattr(flow, "client", api)
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(Bot, "__call__", sent)
    fixed = AsyncMock(return_value={"run_id": "a" * 32, "status": "queued", "delivery": []})
    monkeypatch.setattr(workflow.backend, "request", fixed)
    # Legacy feature HTTP is faked, but the real registered handlers dispatch it.
    http_calls = []
    def respond(request):
        http_calls.append(request)
        if request.url.path == "/tasks/start":
            return httpx.Response(200, json={"status": "need_info", "session_id": "s", "questions": [{"key": "product", "question": "Что за продукт?"}]})
        return httpx.Response(200, json=[])
    patch_http(monkeypatch, respond)
    async def check():
        dp, bot = create_dispatcher(), Bot("123456:offline-token")
        date = datetime.now(timezone.utc)
        user = types.User(id=123, is_bot=False, first_name="User")
        chat = types.Chat(id=123, type="private")
        def update(mid, text):
            return types.Update(update_id=mid, message=types.Message(message_id=mid, date=date, chat=chat, from_user=user, text=text))
        def callback(mid, data):
            return types.Update(update_id=mid, callback_query=types.CallbackQuery(id=str(mid), from_user=user, chat_instance="instance", data=data,
                message=types.Message(message_id=mid, date=date, chat=chat, from_user=types.User(id=bot.id, is_bot=True, first_name="Bot"))))
        try:
            # Concurrent duplicate updates serialize under the real FSM middleware.
            await asyncio.gather(dp.feed_update(bot, update(1, "Стратегия")), dp.feed_update(bot, update(1, "Стратегия")))
            assert api.execute.await_count == 1
            await dp.feed_update(bot, update(2, "/analyze https://competitor.example"))
            assert fixed.call_args.args[:2] == ("POST", "/workflows")
            await dp.feed_update(bot, callback(3, "agent_strategy"))
            await dp.feed_update(bot, update(4, "Standalone task"))
            assert http_calls[-1].url.path == "/tasks/start"
            await dp.feed_update(bot, callback(5, "generate_image"))
            fsm = dp.fsm.get_context(bot=bot, chat_id=123, user_id=123)
            assert await fsm.get_state() == agent_flow.ImageStates.waiting_platform.state
            await dp.feed_update(bot, update(6, "telegram"))
            assert await fsm.get_state() == agent_flow.ImageStates.waiting_use_case.state
            await dp.feed_update(bot, update(7, "/new"))
            assert await fsm.get_state() is None
            await dp.feed_update(bot, update(8, "/history"))
            assert http_calls[-1].url.path == "/tasks/by_user/123"
            assert api.execute.await_count == 1
        finally:
            await bot.session.close()
            await dp.storage.close()
            await dp.fsm.events_isolation.close()
            for router in dp.sub_routers:
                router._parent_router = None
    asyncio.run(check())


@pytest.mark.parametrize("outcome", ["UNSAFE_SOURCE", "SOURCE_UNAVAILABLE", "EMPTY_CONTENT", "CAPABILITY_UNAVAILABLE", "INVALID_EXTRACTION"])
def test_owned_acquisition_failure_offers_manual_context(monkeypatch, outcome):
    api = SimpleNamespace(execute=AsyncMock(return_value=dto.NeedsInputResponse(code="missing",
        alternatives=[["product_truth"]], owned_site=dto.OwnedSiteResult(outcome=outcome))))
    monkeypatch.setattr(flow, "client", api)
    async def check():
        fsm, msg = context(), message()
        await flow.receive(msg, fsm)
        assert "вручную" in text_sent(msg) and outcome not in text_sent(msg)
        assert (await fsm.get_data())["copilot_pending"]["fields"] == ["product_truth"]
    asyncio.run(check())


@pytest.mark.parametrize("change", [None, {"internal_stage": "PRIVATE_SENTINEL"}, {"kind": "MODULE_RESULT"},
    {"schema_version": "wrong"}, {"code": "temporarily_unavailable"}, {"code": "unknown"},
    "kind", "schema_version", "owned_site", "code", "code_only", "non_json"])
def test_execution_invalid_http_envelope_fails_closed(monkeypatch, caplog, change):
    body = dto.ErrorResponse(code="execution_invalid").model_dump(mode="json")
    if change == "code_only":
        body = {"code": "execution_invalid"}
    elif change == "non_json":
        body = "PRIVATE_SENTINEL"
    elif isinstance(change, str):
        body.pop(change)
    elif change:
        body.update(change)
    patch_http(monkeypatch, lambda _: httpx.Response(500, text=body) if change == "non_json" else httpx.Response(500, json=body))
    with pytest.raises(CopilotError) as caught:
        asyncio.run(CopilotClient().execute(123, dto.ExecuteRequest(request_key="k", message="text")))
    assert caught.value.category == ("execution_invalid" if change is None else "server")
    assert caught.value.status == 500
    assert "PRIVATE_SENTINEL" not in str(caught.value) + caplog.text


@pytest.mark.parametrize("status", [500, 503])
def test_real_http_flow_terminal_output_and_transient_retry(monkeypatch, status):
    calls = []
    def respond(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(status, json=dto.ErrorResponse(code="execution_invalid" if status == 500 else "temporarily_unavailable").model_dump(mode="json"))
        return httpx.Response(200, json=started().model_dump(mode="json"))
    patch_http(monkeypatch, respond)
    monkeypatch.setattr(flow, "client", CopilotClient())
    async def check():
        state, msg = context(), message()
        await flow.receive(msg, state)
        assert (await state.get_data())["copilot_pending"]["phase"] == ("stopped" if status == 500 else "retry")
        buttons = [button.text for row in msg.answer.call_args.kwargs["reply_markup"].inline_keyboard for button in row]
        assert buttons == (["Начать новый запрос", "Отмена"] if status == 500 else ["Повторить", "Начать новый запрос", "Отмена"])
        if status == 500:
            assert text_sent(msg) == "Не удалось получить корректный результат выполнения. Начните новый запрос или сообщите администратору."
        await click(state, msg, "retry")
        if status == 500:
            assert len(calls) == 1
            assert "Повторить" not in str(msg.answer.call_args_list)
            await click(state, msg, "new", "new")
            await flow.receive(message(mid=2), state)
            assert json.loads(calls[0].content)["request_key"] != json.loads(calls[1].content)["request_key"]
        else:
            assert len(calls) == 2 and calls[0].content == calls[1].content
    asyncio.run(check())


@pytest.mark.parametrize("count", [5, 30])
def test_compact_confirmation_displays_and_confirms_exact_candidates(monkeypatch, count):
    candidates = [dto.ConfirmationCandidate(statement_id=f"statement.fact{i}",
        field="stated_features_capabilities", statement=f"Сведение о бизнесе {i}",
        source_url="https://own.example") for i in range(count)]
    result = dto.OwnedSiteResult(outcome="ACQUIRED", snapshot_id="snapshot.current", candidates=candidates)
    api = SimpleNamespace(execute=AsyncMock(side_effect=[dto.NeedsInputResponse(code="missing",
        alternatives=[["product_truth"]], owned_site=result), started()]))
    monkeypatch.setattr(flow, "client", api)
    async def check():
        state, msg = context(), message("Стратегия https://own.example")
        await flow.receive(msg, state)
        msg.answer.reset_mock()
        await click(state, msg, "own", "own")
        msg.answer.assert_awaited_once()
        block = text_sent(msg)
        buttons = [b.text for row in msg.answer.call_args.kwargs["reply_markup"].inline_keyboard for b in row]
        assert buttons == ["Всё актуально", "Исправить сведения", "Отмена"]
        assert block.count("https://own.example") == block.count("Источник:") == 1
        assert all(term not in block for term in ("SITE_CLAIM", "CONFIRMED_BUSINESS_FACT",
            "site_claim", "statement_id", "snapshot_id", "product_truth", "snapshot.current", "statement.fact"))
        displayed = candidates[:min(count, flow.CONFIRMATION_CANDIDATE_LIMIT)]
        assert [line for line in block.splitlines() if line.startswith("• ")] == ["• " + c.statement for c in displayed]
        if count > len(displayed):
            assert "только к пунктам выше" in block
        callback = await click(state, msg, "confirm", "yes")
        confirmation = api.execute.call_args.args[1].confirmation
        assert confirmation.statement_ids == [c.statement_id for c in displayed]
        assert confirmation.snapshot_id == result.snapshot_id and confirmation.confirmed is True
        assert confirmation.reference.startswith("tg-confirm:")
        await flow.callback_action(callback, state)
        assert api.execute.await_count == 2
        assert "устарело" in callback.answer.call_args.args[0]
    asyncio.run(check())


def test_correct_information_enters_existing_manual_flow(monkeypatch):
    api = SimpleNamespace(execute=AsyncMock(side_effect=[dto.NeedsInputResponse(code="missing",
        alternatives=[["product_truth"]], owned_site=owned()), started()]))
    monkeypatch.setattr(flow, "client", api)
    async def check():
        state, msg = context(), message("Стратегия https://own.example")
        await flow.receive(msg, state)
        await click(state, msg, "own", "own")
        old = await click(state, msg, "manual", "manual")
        pending = (await state.get_data())["copilot_pending"]
        assert pending["phase"] == "fields" and pending["fields"] == ["product_truth"]
        assert "confirmation" not in pending["payload"]
        old.data = old.data.replace(":manual", ":confirm")
        old.id = "stale-confirm"
        await flow.callback_action(old, state)
        assert api.execute.await_count == 1
        await flow.receive(message("Новые сведения", mid=2), state)
        payload = api.execute.call_args.args[1]
        assert payload.context.product_truth == "Новые сведения" and payload.confirmation is None
    asyncio.run(check())


@pytest.mark.parametrize("changed", [False, True])
@pytest.mark.parametrize("statements", [[], [" "], ["🙂" * 2000]])
def test_no_displayable_confirmation_falls_back_to_manual(monkeypatch, changed, statements):
    result = dto.OwnedSiteResult(outcome="ACQUIRED", snapshot_id="snapshot.empty", candidates=[
        dto.ConfirmationCandidate(statement_id=f"statement.{i}", field="stated_product_service",
            statement=text, source_url="https://own.example") for i, text in enumerate(statements)])
    responses = [dto.NeedsInputResponse(code="missing", alternatives=[["product_truth"]], owned_site=owned()),
        CopilotError("confirmation_changed", owned_site=result)] if changed else [
        dto.NeedsInputResponse(code="missing", alternatives=[["product_truth"]], owned_site=result)]
    api = SimpleNamespace(execute=AsyncMock(side_effect=responses))
    monkeypatch.setattr(flow, "client", api)
    async def check():
        state, msg = context(), message("Стратегия https://own.example")
        await flow.receive(msg, state)
        await click(state, msg, "own", "own")
        if changed:
            await click(state, msg, "confirm", "confirm")
        pending = (await state.get_data())["copilot_pending"]
        assert pending["phase"] == "fields" and pending["fields"] == ["product_truth"]
        assert "confirmation" not in pending["payload"]
        assert "свойства продукта" in msg.answer.call_args.args[0]
    asyncio.run(check())


def test_confirmation_length_budget_preserves_whole_statements(monkeypatch):
    candidates = [dto.ConfirmationCandidate(statement_id=f"statement.{i}", field="stated_product_service",
        statement=text, source_url="https://own.example/" + "x" * 1900)
        for i, text in enumerate(["🙂" * 2000, "Полный день " + "🙂" * 700, "Питание " + "🙂" * 700, "Есть пробный день"])]
    result = dto.OwnedSiteResult(outcome="ACQUIRED", snapshot_id="snapshot.long", candidates=candidates)
    api = SimpleNamespace(execute=AsyncMock(side_effect=[dto.NeedsInputResponse(code="missing",
        alternatives=[["product_truth"]], owned_site=result), started()]))
    monkeypatch.setattr(flow, "client", api)
    async def check():
        state, msg = context(), message("Стратегия https://own.example")
        await flow.receive(msg, state)
        msg.answer.reset_mock()
        await click(state, msg, "own", "own")
        msg.answer.assert_awaited_once()
        block = text_sent(msg)
        assert len(block.encode("utf-16-le")) // 2 <= 3500
        assert [line for line in block.splitlines() if line.startswith("• ")] == ["• " + c.statement for c in candidates[1:]]
        assert block.count("Источник:") <= 1
        await click(state, msg, "confirm", "confirm")
        assert api.execute.call_args.args[1].confirmation.statement_ids == [c.statement_id for c in candidates[1:]]
    asyncio.run(check())
