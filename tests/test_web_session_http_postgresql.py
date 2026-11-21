"""HTTP boundary on real 0016. Only the downstream B3/B4 reader is substituted."""
import asyncio
import uuid

import pytest
from sqlalchemy import delete, event, func, select

from app import web_session_dto as dto
from app.db import get_session
from app.main import app
from app.models import User, WebSession
from app.routers.web_sessions import membership_reader
from app.services import web_auth
from app.config import settings
from app.web_security import ATTEMPT, SESSION
from tests.postgresql_support import mvp_database
from tests.test_web_session_http import EXAMPLE, ORIGIN, client, configured, validate


def test_browser_lifecycle(mvp_database, configured, monkeypatch, caplog):
    actor = uuid.uuid4().int >> 80
    sensitive = []
    fail_commit = False

    async def database():
        async with mvp_database() as db:
            if fail_commit:
                def fail(_):
                    raise RuntimeError("sensitive-commit-details")
                event.listen(db.sync_session, "before_commit", fail, once=True)
            yield db

    monkeypatch.setitem(app.dependency_overrides, get_session, database)

    async def run():
        nonlocal fail_commit
        async with mvp_database.begin() as db:
            user = User(telegram_id=actor)
            db.add(user)
            await db.flush()
            owner = user.id

        async def from_contract(db, user_id, login):
            assert user_id == owner
            return [dto.OrganizationMembership.model_validate(EXAMPLE["me"]["memberships"][0])]

        async def prepare(browser):
            async with mvp_database.begin() as db:
                issued = await web_auth.issue(db, actor)
            response = await browser.post("/v2/auth/telegram/challenge", json={"token": issued.secret})
            assert response.status_code == 200
            validate("TelegramBrowserChallenge", response.json())
            cookie = response.headers["set-cookie"]
            assert all(flag in cookie for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age="))
            assert "domain=" not in cookie.lower()
            code = response.json()["confirmation_code"]
            sensitive.extend([issued.secret, code, browser.cookies[ATTEMPT]])
            async with mvp_database.begin() as db:
                await web_auth.confirm(db, actor, code)
            return {"token": issued.secret}

        async def exchange(browser, body):
            return await browser.post("/v2/auth/telegram/exchange", json=body)

        try:
            async with client() as browser, client() as neighbor:
                browser.headers["Origin"] = neighbor.headers["Origin"] = ORIGIN
                body = await prepare(browser)
                neighbor.cookies.set(ATTEMPT, "wrong")
                assert (await exchange(neighbor, body)).status_code == 401
                # Production reader is deliberately closed until B3/B4.
                r = await exchange(browser, body)
                assert r.status_code == 503 and "set-cookie" not in r.headers
                async with mvp_database() as db:
                    assert await db.scalar(select(func.count()).select_from(WebSession).where(
                        WebSession.user_id == owner)) == 0
                monkeypatch.setitem(app.dependency_overrides, membership_reader, lambda: from_contract)
                fail_commit = True
                r = await exchange(browser, body)
                assert r.status_code == 503 and "set-cookie" not in r.headers
                assert "sensitive-commit-details" not in r.text
                fail_commit = False
                neighbor.cookies.clear()
                neighbor.cookies.update(browser.cookies)
                replies = await asyncio.gather(exchange(browser, body), exchange(neighbor, body))
                assert sorted(r.status_code for r in replies) == [200, 401]
                winner = next(r for r in replies if r.status_code == 200)
                validate("AuthSession", winner.json())
                assert winner.json()["me"]["user"]["id"] == owner
                assert winner.headers["cache-control"] == "private, no-store"
                issued_cookie, cleared_attempt = winner.headers.get_list("set-cookie")
                assert issued_cookie.startswith(SESSION + "=") and "Domain=" not in issued_cookie
                assert all(flag in issued_cookie for flag in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"))
                assert ATTEMPT in cleared_attempt and "Max-Age=0" in cleared_attempt
                browser.cookies.clear()
                browser.cookies.update(winner.cookies)
                neighbor.cookies.clear()
                neighbor.cookies.update(browser.cookies)
                sensitive.append(browser.cookies[SESSION])
                old = winner.json()["csrf_token"]
                sensitive.append(old)
                monkeypatch.setattr(settings, "WEB_TELEGRAM_LOGIN_ENABLED", False)
                for tab in (browser, neighbor):
                    response = await tab.get("/v2/auth/csrf")
                    validate("CsrfToken", response.json())
                    assert response.json()["csrf_token"] == old
                    validate("Me", (await tab.get("/v2/me")).json())
                assert (await neighbor.post("/v2/auth/logout")).status_code == 403
                monkeypatch.setattr(settings, "WEB_TELEGRAM_LOGIN_ENABLED", True)
                rotated = await exchange(browser, await prepare(browser))
                assert rotated.status_code == 200
                assert (await neighbor.get("/v2/auth/csrf")).status_code == 401
                assert (await browser.post("/v2/auth/logout", headers={"X-CSRF-Token": old})).status_code == 403
                new = rotated.json()["csrf_token"]
                assert new != old
                sensitive.extend([browser.cookies[SESSION], new])
                monkeypatch.setattr(settings, "WEB_TELEGRAM_LOGIN_ENABLED", False)
                neighbor.cookies.clear()
                neighbor.cookies.update(browser.cookies)
                logout, touch = await asyncio.gather(browser.post("/v2/auth/logout", headers={"X-CSRF-Token": new}),
                                                    neighbor.get("/v2/auth/csrf"))
                assert logout.status_code == 204 and logout.content == b""
                assert "Max-Age=0" in logout.headers["set-cookie"]
                assert touch.status_code in (200, 401)
                assert (await neighbor.get("/v2/me")).status_code == 401
                assert (await neighbor.post("/v2/auth/logout")).status_code == 204
        finally:
            async with mvp_database.begin() as db:
                await db.execute(delete(User).where(User.id == owner))

    asyncio.run(run())
    assert all(secret not in caplog.text for secret in sensitive + ["sensitive-commit-details"])
