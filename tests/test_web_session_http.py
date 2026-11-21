"""ASGI client, no network. Public schema snapshot from web db1135fc (see B2.2 notes)."""
import asyncio
import hashlib
import hmac
import base64
import json
from pathlib import Path

import httpx
import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import SecretStr
from sqlalchemy.exc import OperationalError

from app import web_session_dto as dto
from app.config import settings
from app.db import get_session
from app.main import app
from app.web_security import origin_key, csrf
from app.models import WebSession

ORIGIN = "https://browser.test"
FIXTURES = Path(__file__).parent / "fixtures/web_sessions"
SCHEMAS = json.loads((FIXTURES / "openapi-schemas.json").read_text(encoding="utf8"))
EXAMPLE = json.loads((FIXTURES / "auth-exchange.200.json").read_text(encoding="utf8"))


def validate(name, value):
    schema = {**SCHEMAS, "$ref": "#/components/schemas/" + name}
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(settings, "WEB_API_ENABLED", True)
    monkeypatch.setattr(settings, "WEB_TELEGRAM_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "WEB_APP_ORIGIN", ORIGIN)
    monkeypatch.setattr(settings, "WEB_CSRF_SECRET", SecretStr("test-server-key-" * 3))


def client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN)


def test_approved_dtos(configured):
    result = dto.AuthSession.model_validate(EXAMPLE).model_dump(mode="json")
    validate("AuthSession", result)
    validate("Me", result["me"])
    row = WebSession(token_hash=hashlib.sha256(b"cookie").hexdigest())
    expected = hmac.digest(("test-server-key-" * 3).encode(),
                           b"brenvio/web-csrf/v1\x00" + bytes.fromhex(row.token_hash), "sha256")
    assert csrf(row) == base64.urlsafe_b64encode(expected).rstrip(b"=").decode()


@pytest.mark.parametrize("origin", ["", "http://host", "https://host/", "https://u:p@host",
                                    "https://*.test", "https://host?", "https://host#",
                                    "https://host:65536", "https://host\\foo", "https://host\n"])
def test_invalid_configuration_origins(origin):
    assert origin_key(origin) is None


@pytest.mark.parametrize("origin,site,ok", [
    (ORIGIN, None, True), (ORIGIN + ":443", "same-origin", True), (None, "same-origin", True),
    (ORIGIN, "cross-site", False), ("https://bad.test", "same-origin", False),
    (None, None, False), ("null", None, False), (None, "same-site", False), (ORIGIN + ":8443", None, False),
])
def test_origin_matrix(configured, origin, site, ok):
    async def run():
        headers = {}
        if origin is not None:
            headers["Origin"] = origin
        if site:
            headers["Sec-Fetch-Site"] = site
        async with client() as browser:
            response = await browser.post("/v2/auth/logout", headers=headers)
            assert response.status_code == (204 if ok else 403)
            assert response.headers["Cache-Control"] == "private, no-store"
            if not ok:
                validate("ErrorResponse", response.json())
                assert "Set-Cookie" not in response.headers
    asyncio.run(run())


@pytest.mark.parametrize("api,login", [(False, False), (False, True), (True, False), (True, True)])
def test_flags(configured, monkeypatch, api, login):
    monkeypatch.setattr(settings, "WEB_API_ENABLED", api)
    monkeypatch.setattr(settings, "WEB_TELEGRAM_LOGIN_ENABLED", login)

    async def run():
        async with client() as browser:
            for path in ["challenge", "exchange"]:
                r = await browser.post("/v2/auth/telegram/" + path, headers={"Origin": ORIGIN},
                                       json={"token": "validation-secret"})
                assert r.status_code == (404 if not api else 422 if login else 403)
                assert "validation-secret" not in r.text
                assert r.headers["cache-control"] == "private, no-store"
            for path in ("/v2/auth/csrf", "/v2/me"):
                assert (await browser.get(path)).status_code == (401 if api else 404)
            response = await browser.post("/v2/auth/logout", headers={"Origin": ORIGIN})
            assert response.status_code == (204 if api else 404)
    asyncio.run(run())


def test_closed_config_bot_credentials_and_db_error(configured, monkeypatch, caplog):
    marker = "never-echo-this-secret"
    async def unavailable_db():
        raise OperationalError("query", {"secret": marker}, RuntimeError(marker))

    monkeypatch.setitem(app.dependency_overrides, get_session, unavailable_db)

    async def run():
        async with client() as browser:
            browser.cookies.set("__Host-brenvio_session", marker)
            for headers in ({"Authorization": "Bearer " + marker}, {"X-Telegram-User-ID": "12"}):
                r = await browser.get("/v2/me", headers=headers)
                assert r.status_code == 401
            for path in ("/v2/me", "/v2/auth/csrf", "/v2/auth/logout"):
                r = await browser.request("POST" if path.endswith("logout") else "GET", path, headers={"Origin": ORIGIN})
                assert r.status_code == 503
                validate("ErrorResponse", r.json())
                assert r.headers["x-request-id"] == r.json()["request_id"]
                assert marker not in r.text and "set-cookie" not in r.headers
                assert r.headers["cache-control"] == "private, no-store"
            monkeypatch.setattr(settings, "WEB_APP_ORIGIN", "http://invalid")
            assert (await browser.post("/v2/auth/logout", headers={"Origin": ORIGIN})).status_code == 503
        assert marker not in caplog.text
    asyncio.run(run())


def test_root_path_preserves_feature_and_origin_guards(configured, monkeypatch):
    async def run():
        transport = httpx.ASGITransport(app=app, root_path="/api")
        async with httpx.AsyncClient(transport=transport, base_url=ORIGIN + "/api/") as browser:
            monkeypatch.setattr(settings, "WEB_API_ENABLED", False)
            r = await browser.post("v2/auth/logout")
            assert r.status_code == 404 and r.headers["cache-control"] == "private, no-store"
            monkeypatch.setattr(settings, "WEB_API_ENABLED", True)
            assert (await browser.post("v2/auth/logout")).status_code == 403
            monkeypatch.setattr(settings, "WEB_TELEGRAM_LOGIN_ENABLED", False)
            r = await browser.post("v2/auth/telegram/challenge", headers={"Origin": ORIGIN})
            assert r.status_code == 403 and r.json()["code"] == "feature_disabled"
    asyncio.run(run())


def test_http_success_schemas_and_required_fields():
    public = app.openapi()
    for path, method, model in [
        ("/v2/auth/telegram/challenge", "post", "TelegramBrowserChallenge"),
        ("/v2/auth/telegram/exchange", "post", "AuthSession"),
        ("/v2/auth/csrf", "get", "CsrfToken"),
        ("/v2/me", "get", "Me"),
    ]:
        response = public["paths"][path][method]["responses"]["200"]
        ref = response["content"]["application/json"]["schema"]["$ref"]
        assert ref.endswith("/" + model)
        actual = public["components"]["schemas"][model]
        approved = SCHEMAS["components"]["schemas"][model]
        assert set(actual["properties"]) == set(approved["properties"])
        assert set(actual["required"]) == set(approved["required"])
