"""Safe operational boundaries, no paid/network providers."""
import asyncio
from contextlib import asynccontextmanager
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.readiness import readiness
from bot.backend import validate_configuration
from tests.test_copilot_api import application, headers
from tests.test_graph_model_adapter import install_transport


@pytest.fixture(autouse=True)
def capture_production_logs(monkeypatch):
    # Alembic roundtrip suites may disable existing loggers via fileConfig.
    for name in ("app.routers.copilot", "app.readiness", "app.llm.openai_text",
                 "app.llm.openai_images", "app.services.qc_shortener"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", False)


@pytest.mark.parametrize("method,path", [("POST", "/copilot/execute"), ("GET", "/copilot/runs"), ("GET", "/copilot/runs/" + "a" * 64)])
def test_database_failure_is_safe_503_not_success(monkeypatch, caplog, method, path):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "api-test")
    failure = OperationalError("SQL PRIVATE_CONTEXT", {"token": "PRIVATE_TOKEN"}, RuntimeError("PRIVATE_DB"))
    api = SimpleNamespace(execute=AsyncMock(side_effect=failure), reader=SimpleNamespace(
        get=AsyncMock(side_effect=failure), recent=AsyncMock(side_effect=failure)))
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application(api)), base_url="http://test") as client:
            response = await client.request(method, path, headers=headers(),
                json={"request_key": "db-down", "message": "secret"} if method == "POST" else None)
            assert response.status_code == 503 and response.json()["code"] == "temporarily_unavailable"
            assert "PRIVATE" not in response.text
    asyncio.run(check())
    assert "PRIVATE" not in caplog.text and "OperationalError" in caplog.text


@pytest.mark.parametrize("available", [False, True])
def test_readiness_requires_database_and_composition_only(available, caplog):
    @asynccontextmanager
    async def sessions():
        yield SimpleNamespace(execute=AsyncMock(side_effect=None if available else OperationalError("PRIVATE", {}, Exception("PRIVATE"))))
    async def check():
        assert not await readiness(None)
        assert await readiness(SimpleNamespace(sessions=sessions)) is available
    asyncio.run(check())
    assert "PRIVATE" not in caplog.text


@pytest.mark.parametrize("name,value", [("API_BASE_URL", "relative"), ("API_BASE_URL", "http://user:SECRET@backend"),
    ("API_BASE_URL", "http://backend?token=SECRET"), ("BOT_BACKEND_TOKEN", " "), ("TELEGRAM_BOT_TOKEN", "SECRET")])
def test_bot_configuration_fails_fast_without_secret(monkeypatch, name, value):
    monkeypatch.setattr(settings, "API_BASE_URL", "http://backend:8000")
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "offline-secret")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123456:offline-token")
    validate_configuration()
    monkeypatch.setattr(settings, name, value)
    with pytest.raises(ValueError) as caught:
        validate_configuration()
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize("kind", ["text", "image", "qc"])
def test_legacy_provider_logging_excludes_raw_contents(monkeypatch, caplog, kind):
    from app.llm.openai_text import chat
    from app.llm.openai_images import generate_image
    from app.services import qc_shortener
    install_transport(monkeypatch, lambda _: httpx.Response(401, json={"error": {"message": "PRIVATE_PROVIDER_BODY"}}))
    monkeypatch.setattr(settings, "HTTP_RETRIES", 0)
    async def check():
        if kind == "qc":
            monkeypatch.setattr(qc_shortener, "openai_chat", AsyncMock(return_value=("PRIVATE_INVALID_OUTPUT", {})))
            await qc_shortener.qc_shorten({"reply": "PRIVATE_PROMPT"})
        else:
            with pytest.raises(httpx.HTTPStatusError):
                if kind == "text":
                    await chat(messages=[{"role": "user", "content": "PRIVATE_PROMPT"}], model="test")
                else:
                    await generate_image("PRIVATE_PROMPT", "1024x1024", "test")
    asyncio.run(check())
    assert "PRIVATE" not in caplog.text and caplog.records


def test_transport_url_logging_disabled_in_production():
    from app.logging import setup_logging
    setup_logging()
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING


def test_framework_tracebacks_and_poll_errors_cannot_log_secrets():
    from app.logging import ContextFilter
    failure = RuntimeError("PRIVATE provider envelope and bearer")
    record = logging.LogRecord("uvicorn.error", logging.ERROR, __file__, 1,
        "Failed PRIVATE request", (), (RuntimeError, failure, None))
    assert ContextFilter().filter(record)
    assert record.getMessage() == "Unhandled exception error_type=RuntimeError" and record.exc_info is None
    polling = logging.LogRecord("aiogram.dispatcher", logging.ERROR, __file__, 1,
        "Failed to fetch updates - %s", ("PRIVATE token",), None)
    assert ContextFilter().filter(polling) and "PRIVATE" not in polling.getMessage()
