import asyncio
from unittest.mock import AsyncMock

from aiogram import Bot
import pytest

from app.config import settings
from bot import backend, project_navigation as nav
from bot.main import create_dispatcher
from tests.test_telegram_navigation import close_dispatcher, update


@pytest.mark.parametrize(
    ("enabled", "mode", "cohort", "onboards"),
    [
        (True, "cohort", frozenset(), False),
        (True, "cohort", frozenset({456}), False),
        (False, "cohort", frozenset({123}), False),
        (True, "cohort", frozenset({123}), True),
        (True, "all-users", frozenset(), True),
        (False, "all-users", frozenset(), False),
    ],
)
def test_start_respects_rollout_mode(monkeypatch, enabled, mode, cohort, onboards):
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_ENABLED", enabled)
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_MODE", mode)
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_COHORT", cohort)
    request = AsyncMock(return_value={"step": "name"})
    menu = AsyncMock()
    monkeypatch.setattr(backend, "request", request)
    monkeypatch.setattr(nav, "show_menu", menu)
    sent = AsyncMock(return_value=update(2, "Prompt").message)
    monkeypatch.setattr(Bot, "__call__", sent)

    async def run():
        dp, bot = create_dispatcher(), Bot("123456:offline-token")
        try:
            await dp.feed_update(bot, update(1, "/start"))
            if onboards:
                request.assert_awaited_once_with("GET", "/workflows/onboarding?include_name=true", 123)
                assert sent.call_args.args[0].text == nav.WELCOME
                menu.assert_not_awaited()
            else:
                request.assert_not_awaited()
                menu.assert_awaited_once()
        finally:
            await close_dispatcher(dp, bot)

    asyncio.run(run())


def test_restore_step_on_new_dispatcher_and_reuse_existing_prompt_after_failure(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_COHORT", frozenset({123}))
    last_message_id = 0

    async def send(method):
        nonlocal last_message_id
        last_message_id += 1
        return update(last_message_id, method.text).message

    sent = AsyncMock(side_effect=send)
    monkeypatch.setattr(Bot, "__call__", sent)
    progress = "name"
    writes = 0

    async def request(method, path, actor, *, payload=None):
        nonlocal progress, writes
        assert actor == 123
        if method == "GET":
            assert path.partition("?")[0] == "/workflows/onboarding"
        elif path == "/workflows/onboarding/name":
            progress = "product"
        elif path.partition("&")[0] == "/workflows/profile?onboarding_step=product":
            writes += 1
            if writes == 1:
                raise backend.BackendError("Unavailable")
            assert payload == {"product_description": "Coffee"}
            progress = "audience"
        elif path.partition("&")[0] == "/workflows/profile?onboarding_step=audience":
            assert payload == {"audience": "Neighbors"}
            progress = "goal"
        elif path.partition("&")[0] == "/workflows/profile?onboarding_step=goal":
            assert payload == {"goals": ["Visitors"]}
            progress = "ready"
        else:
            raise AssertionError(path)
        return {"step": progress}

    async def feed(dp, bot, message_id, text):
        nonlocal last_message_id
        last_message_id = max(last_message_id, message_id)
        await dp.feed_update(bot, update(message_id, text))

    async def run():
        first, bot = create_dispatcher(), Bot("123456:offline-token")
        try:
            await feed(first, bot, 1, "/start")
            await feed(first, bot, 3, "Preferred")
            await feed(first, bot, 5, "Coffee")
            assert sent.call_args.args[0].reply_parameters.message_id == 5
            assert progress == "product"
        finally:
            await close_dispatcher(first, bot)
        second, bot = create_dispatcher(), Bot("123456:offline-token")
        try:
            await feed(second, bot, 7, "/start")
            assert sent.call_args.args[0].text == nav.ONBOARDING_QUESTIONS["product"]
            await feed(second, bot, 9, "Coffee")
            assert sent.call_args.args[0].text == nav.ONBOARDING_QUESTIONS["audience"]
            await feed(second, bot, 9, "Coffee")  # redelivery
            await feed(second, bot, 10, "Coffee")  # queued before the audience prompt
            assert progress == "audience"
            await feed(second, bot, 11, "Neighbors")
            await feed(second, bot, 13, "Visitors")
            assert sent.call_args.args[0].text == nav.ONBOARDING_COMPLETE
            await feed(second, bot, 13, "Visitors")
            assert progress == "ready"
        finally:
            await close_dispatcher(second, bot)

    monkeypatch.setattr(backend, "request", request)
    asyncio.run(run())


def test_startup_rejects_mismatched_backend_rollout(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_MODE", "all-users")
    request = AsyncMock(return_value={"signature": "disabled"})
    monkeypatch.setattr(backend, "request", request)
    with pytest.raises(RuntimeError, match="differs between bot and backend"):
        asyncio.run(backend.validate_onboarding_configuration())
    request.assert_awaited_once_with("GET", "/workflows/onboarding/config", None)
    request.return_value = {"signature": "all-users"}
    asyncio.run(backend.validate_onboarding_configuration())
