import asyncio
from unittest.mock import AsyncMock

from aiogram import Bot, types
import pytest

from app.config import settings
from bot import backend, project_navigation as nav
from bot.main import create_dispatcher
from tests.test_telegram_navigation import close_dispatcher, update


@pytest.mark.parametrize(
    ("enabled", "cohort", "onboards"),
    [
        (True, frozenset(), False),
        (True, frozenset({456}), False),
        (False, frozenset({123}), False),
        (True, frozenset({123}), True),
    ],
)
def test_start_respects_explicit_cohort(monkeypatch, enabled, cohort, onboards):
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_ENABLED", enabled)
    monkeypatch.setattr(settings, "TELEGRAM_ONBOARDING_COHORT", cohort)
    request = AsyncMock(return_value={"step": "name"})
    menu = AsyncMock()
    monkeypatch.setattr(backend, "request", request)
    monkeypatch.setattr(nav, "show_menu", menu)
    monkeypatch.setattr(Bot, "__call__", AsyncMock(return_value=True))

    async def run():
        dp, bot = create_dispatcher(), Bot("123456:offline-token")
        try:
            await dp.feed_update(bot, update(1, "/start"))
            if onboards:
                request.assert_awaited_once_with("GET", "/workflows/onboarding", 123)
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
    sent = AsyncMock(return_value=True)
    monkeypatch.setattr(Bot, "__call__", sent)
    progress = "name"
    writes = 0

    async def request(method, path, actor, *, payload=None):
        nonlocal progress, writes
        assert actor == 123
        if method == "GET":
            assert path == "/workflows/onboarding"
        elif path == "/workflows/onboarding/name":
            progress = "product"
        elif path == "/workflows/profile?onboarding_step=product":
            writes += 1
            if writes == 1:
                raise backend.BackendError("Unavailable")
            assert payload == {"product_description": "Coffee"}
            progress = "audience"
        else:
            raise AssertionError(path)
        return {"step": progress}

    def reply(bot, message_id, answer, step):
        item = update(message_id, answer)
        prompt = update(message_id - 1, nav.ONBOARDING_QUESTIONS[step]).message
        prompt = prompt.model_copy(update={"from_user": types.User(id=bot.id, first_name="Assistant", is_bot=True)})
        return item.model_copy(update={"message": item.message.model_copy(update={"reply_to_message": prompt})})

    async def run():
        first, bot = create_dispatcher(), Bot("123456:offline-token")
        try:
            await first.feed_update(bot, update(1, "/start"))
            await first.feed_update(bot, reply(bot, 3, "Preferred", "name"))
            await first.feed_update(bot, reply(bot, 5, "Coffee", "product"))
            assert progress == "product"
        finally:
            await close_dispatcher(first, bot)
        second, bot = create_dispatcher(), Bot("123456:offline-token")
        try:
            await second.feed_update(bot, update(7, "/start"))
            assert sent.call_args.args[0].text == nav.ONBOARDING_QUESTIONS["product"]
            await second.feed_update(bot, reply(bot, 9, "Coffee", "product"))
            assert sent.call_args.args[0].text == nav.ONBOARDING_QUESTIONS["audience"]
        finally:
            await close_dispatcher(second, bot)

    monkeypatch.setattr(backend, "request", request)
    asyncio.run(run())
