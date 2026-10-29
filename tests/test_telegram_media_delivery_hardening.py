"""Offline media trust-boundary and independent delivery regression evidence."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage

from bot import backend, delivery


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("url", [None, 123, "https://evil.example/images/a.png", "//evil.example/images/a.png", "/tasks/1", "/images/../tasks/1", "/images/a.png?token=secret", "http://user:pass@test/images/a.png"])
def test_image_rejects_untrusted_url_before_sending_credentials(monkeypatch, url):
    monkeypatch.setattr(backend.settings, "API_BASE_URL", "http://test")
    calls = []
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request))) as client:
            with pytest.raises(backend.BackendError):
                await backend.fetch_image(client, url, 123)
        assert calls == []
    run(check())


def test_image_streams_owned_backend_resource_and_rejects_redirect(monkeypatch):
    monkeypatch.setattr(backend.settings, "API_BASE_URL", "http://test")
    def handler(request):
        assert request.headers["X-Telegram-User-ID"] == "123"
        return httpx.Response(302, headers={"location": "https://evil.example/file"})
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            with pytest.raises(backend.BackendError):
                await backend.fetch_image(client, "/images/a.png", 123)
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"png"))) as client:
            assert await backend.fetch_image(client, "http://test/images/a.png", 123) == b"png"
    run(check())


def test_image_rejects_declared_and_streamed_oversize(monkeypatch):
    monkeypatch.setattr(backend.settings, "API_BASE_URL", "http://test")
    monkeypatch.setattr(backend, "MAX_IMAGE_BYTES", 4)
    async def check():
        for response in (httpx.Response(200, headers={"content-length": "5"}), httpx.Response(200, content=b"12345")):
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: response)) as client:
                with pytest.raises(backend.BackendError):
                    await backend.fetch_image(client, "/images/a.png", 123)
    run(check())


@pytest.mark.parametrize("response", [httpx.Response(200, text="not json"), httpx.Response(200, json=None), httpx.Response(500, json={"detail": "SQL secret traceback"}), httpx.Response(422, json=["wrong schema"])])
def test_backend_errors_are_controlled_and_do_not_expose_response(monkeypatch, response):
    real_client = httpx.AsyncClient
    monkeypatch.setattr(backend.settings, "API_BASE_URL", "http://test")
    monkeypatch.setattr(backend.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(lambda r: response), **kw))
    async def check():
        with pytest.raises(backend.BackendError) as error:
            await backend.request("GET", "/workflows", 123)
        assert "SQL" not in str(error.value)
    run(check())


@pytest.mark.parametrize("outcome", ["success", "retry_after", "send_failure", "lost_ack", "cancel"])
def test_delivery_acks_current_claim_without_regeneration(monkeypatch, outcome):
    monkeypatch.setattr(delivery.settings, "API_BASE_URL", "http://test")
    calls, acks = [], []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/claim"):
            return httpx.Response(200, json={"delivery_id": "d1", "claim_token": "fenced-token", "telegram_id": 123, "payload": {"kind": "text", "text": "saved"}})
        import json
        acks.append(json.loads(request.content))
        if outcome == "lost_ack":
            raise httpx.ReadTimeout("ack unknown")
        return httpx.Response(200, json={"ok": True})
    error = {"retry_after": TelegramRetryAfter(method=SendMessage(chat_id=123, text="saved"), message="wait", retry_after=45), "send_failure": RuntimeError("offline"), "cancel": asyncio.CancelledError()}.get(outcome)
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=error, return_value=SimpleNamespace(message_id=9)))
    async def check():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            if outcome in {"lost_ack", "cancel"}:
                with pytest.raises(httpx.ReadTimeout if outcome == "lost_ack" else asyncio.CancelledError):
                    await delivery.deliver_once(bot, client)
            else:
                assert await delivery.deliver_once(bot, client)
        if outcome == "cancel":
            assert not acks
        else:
            assert acks[0]["claim_token"] == "fenced-token"
            if outcome == "retry_after":
                assert acks[0]["retry_after"] == 45 and acks[0]["retryable"]
            elif outcome == "send_failure":
                assert acks[0]["retryable"] and "message_id" not in acks[0]
            else:
                assert acks[0]["message_id"] == 9
        assert all("delivery" in path for path in calls)
    run(check())
