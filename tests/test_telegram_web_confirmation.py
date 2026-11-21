import asyncio
import os
from unittest.mock import AsyncMock
from urllib.parse import urlsplit

import pytest
from aiogram import Bot
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.db import get_session
from app.main import app
from app.models import BrandProfile, User
from bot import backend
from bot.handlers.web_login import LOGIN
from bot.main import create_dispatcher
from bot.project_navigation import main_keyboard
from tests.postgresql_support import mvp_database
from tests.test_telegram_navigation import close_dispatcher, update
from tests.test_web_auth_postgresql import actors
from tests.test_web_session_http import ORIGIN, client, configured, validate


def test_dispatch_private_sender_only(configured, monkeypatch):
    calls = AsyncMock(return_value=None)
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(backend, "request", calls)
    monkeypatch.setattr(Bot, "__call__", send)
    code = "a" * 22

    async def run():
        dp, bot = create_dispatcher(), Bot("123456:offline-login")
        try:
            await dp.feed_update(bot, update(1, "/confirm " + code, chat_type="group", chat_id=-99))
            calls.assert_not_awaited()
            await dp.feed_update(bot, update(2, "/confirm " + code, actor=124))
            calls.assert_awaited_once_with("POST", "/internal/identity/web-login-confirm", 124,
                                           payload={"confirmation_code": code})
            calls.side_effect = backend.BackendError("unavailable")
            await dp.feed_update(bot, update(3, LOGIN, actor=123))
            assert "недоступна" in send.call_args.args[0].text
            assert LOGIN in str(main_keyboard(private_login=True))
            monkeypatch.setattr(settings, "WEB_TELEGRAM_LOGIN_ENABLED", False)
            assert LOGIN not in str(main_keyboard(private_login=True))
            await dp.feed_update(bot, update(4, "/confirm " + code))
            assert calls.await_count == 2
            assert code not in str(send.call_args_list)
        finally:
            await close_dispatcher(dp, bot)
    asyncio.run(run())


@pytest.fixture(params=[False, True], ids=["empty-brand", "telegram-brand"])
def initial_brand(request, mvp_database, actors):
    if not request.param:
        yield None
        return

    async def seed():
        async with mvp_database.begin() as db:
            uid = await db.scalar(select(User.id).where(User.telegram_id == actors[0]))
            profile = BrandProfile(user_id=uid, brand_name="Original Telegram brand")
            db.add(profile)
            await db.flush()
            return profile.id

    async def cleanup(profile_id):
        async with mvp_database.begin() as db:
            await db.execute(delete(BrandProfile).where(BrandProfile.id == profile_id))

    profile_id = asyncio.run(seed())
    try:
        yield "Original Telegram brand"
    finally:
        asyncio.run(cleanup(profile_id))


def test_internal_confirmation_flow(mvp_database, actors, configured, monkeypatch, caplog, initial_brand):
    redis_url = os.environ.get("REDIS_TEST_URL")
    if not redis_url:
        pytest.skip("disposable Redis required")
    monkeypatch.setattr(settings, "REDIS_URL", redis_url)
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "trusted-test-bot")

    async def database():
        async with mvp_database() as db:
            yield db
    monkeypatch.setitem(app.dependency_overrides, get_session, database)
    issue = "/internal/identity/web-login-link"
    confirm = "/internal/identity/web-login-confirm"
    owner, stranger = map(backend.actor_headers, actors)

    async def run():
        async with client() as bot, client() as browser, client() as other:
            assert (await bot.post(issue)).status_code == 401
            assert (await bot.post(confirm, json={"confirmation_code": "X"*22})).status_code == 401
            browser.headers["Origin"] = other.headers["Origin"] = ORIGIN
            grant = (await bot.post(issue, headers=owner)).json()
            url = urlsplit(grant["url"])
            assert not url.query and url.fragment.startswith("t=")
            token = {"token": url.fragment[2:]}
            begin = "/v2/auth/telegram/challenge"
            result = await browser.post(begin, json=token)
            code = {"confirmation_code": result.json()["confirmation_code"]}
            assert (await other.post(begin, json=token)).status_code == 401
            assert (await bot.post(confirm, headers=stranger, json=code)).status_code == 401
            replies = await asyncio.gather(*(bot.post(confirm, headers=owner, json=code) for _ in range(2)))
            assert sorted(r.status_code for r in replies) == [204, 401]
            exchange = "/v2/auth/telegram/exchange"
            assert (await other.post(exchange, json=token)).status_code == 401
            session = await browser.post(exchange, json=token)
            assert session.status_code == 200
            assert session.json()["me"]["memberships"][0]["role"] == "owner"
            validate("AuthSession", session.json())
            me = (await browser.get("/v2/me")).json()
            validate("Me", me)
            assert me["user"] == session.json()["me"]["user"]
            org_id = me["memberships"][0]["organization"]["id"]
            listing = (await browser.get(f"/v2/orgs/{org_id}/projects")).json()
            validate("ProjectList", listing)
            [default] = listing["items"]
            assert default["brand"]["brand_name"] == initial_brand
            assert bool(default["brand"]["imported_from"]) == bool(initial_brand)
            assert (await browser.post(exchange, json=token)).status_code == 401
            for _ in range(9):
                assert (await bot.post(confirm, headers=stranger, json=code)).status_code == 401
            assert (await bot.post(confirm, headers=stranger, json=code)).status_code == 429
            assert token["token"] not in caplog.text and code["confirmation_code"] not in caplog.text

    asyncio.run(run())


def test_internal_store_failure(configured, monkeypatch):
    from app.routers.internal_web_login import limit_confirm
    class FailingDB:
        def begin(self):
            raise OperationalError("sql", {}, RuntimeError("sensitive value"))
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "test-backend")
    monkeypatch.setitem(app.dependency_overrides, get_session, FailingDB)
    monkeypatch.setitem(app.dependency_overrides, limit_confirm, lambda: 1)

    async def run():
        async with client() as bot:
            for path in ("web-login-link", "web-login-confirm"):
                r = await bot.post("/internal/identity/" + path, headers=backend.actor_headers(1),
                                   json={"confirmation_code": "X"*22})
                assert r.status_code == 503 and "sensitive value" not in r.text
    asyncio.run(run())
