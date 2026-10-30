"""Credential/actor validation and bounded project HTTP routes without I/O."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from app.config import settings
from app.marketing_copilot.api_errors import CopilotAPIError
from app.routers.projects import router, service


def test_projects_http_authentication_private_scope_and_validation(monkeypatch):
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "project-test")
    fake = SimpleNamespace(current=AsyncMock(return_value={"version": 0, "active": None}),
        switch=AsyncMock(return_value={"version": 1, "active": None, "restored_components": []}),
        message=AsyncMock(return_value={"reply": "ok", "public_id": "t:1", "session_id": "a" * 32}),
        history=SimpleNamespace(recent=AsyncMock(return_value={"items": [], "next_offset": None}), get=AsyncMock()))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[service] = lambda: fake
    headers = {"authorization": "Bearer project-test", "x-telegram-user-id": "123"}
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await client.get("/projects/history")).status_code == 401
            assert (await client.get("/projects/history", headers=headers)).json() == {"items": [], "next_offset": None}
            assert (await client.get("/projects/context?chat_id=123", headers=headers)).json() == {"version": 0, "active": None}
            for query in ("limit=51", "offset=10001", "source_type=raw", "query=" + "x" * 101):
                assert (await client.get("/projects/history?" + query, headers=headers)).status_code == 422
            for source in ("g:bad", "t:0", "r:abc", "l:other"):
                assert (await client.get("/projects/items/" + source, headers=headers)).status_code in (404, 422)
            payload = {"chat_id": 123, "expected_version": 0, "request_key": "tg:123:123:1", "text": "continue"}
            for text in ("\x00bad", "\ud800", "x" * 2001, ""):
                assert (await client.post("/projects/context/messages", headers={**headers, "content-type": "application/json"}, content=json.dumps({**payload, "text": text}))).status_code == 422
            assert fake.message.await_count == 0
            response = await client.post("/projects/context/messages", headers=headers, json=payload)
            assert response.status_code == 200 and response.json()["reply"] == "ok"
            fake.switch.side_effect = CopilotAPIError(409, "stale_context")
            response = await client.post("/projects/context", headers=headers,
                json={"chat_id": 123, "expected_version": 0, "public_id": "t:1"})
            assert response.status_code == 409 and response.json()["code"] == "stale_context"
    asyncio.run(exercise())
