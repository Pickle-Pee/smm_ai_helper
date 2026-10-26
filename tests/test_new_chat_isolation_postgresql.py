"""New-request epochs preserve actor identity while isolating chat memory."""
import asyncio
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select

from app.marketing_copilot.api_errors import CopilotAPIError
from app.models import Conversation, Message, User
from app.services.chat_memory_service import ChatMemoryService
from app.services.chat_service import ChatService
from app.services.project_context_service import ProjectContextService
from app.services.project_history_service import ProjectHistoryService
from tests.postgresql_support import mvp_database


def test_new_general_dialogues_do_not_read_legacy_or_previous_epoch(mvp_database, monkeypatch):
    monkeypatch.setattr("app.services.chat_service.scope_guard", AsyncMock(return_value=(True, None)))
    async def exercise():
        actor = int(uuid.uuid4().hex[:12], 16)
        identity = f"tg:{actor}"
        context = ProjectContextService(mvp_database, ProjectHistoryService(mvp_database))
        packets = []
        async def generate(**kwargs):
            packets.append(kwargs)
            return {"reply": "Advice for this dialogue", "follow_up_question": None, "actions": []}
        async def summarize(**kwargs):
            # Capture the actual persisted conversation handed to compaction.
            assert kwargs["conversation"].user_id.startswith(identity + ":new:")
            assert "LEGACY_BUSINESS" not in json.dumps(kwargs["last_messages"])
            return SimpleNamespace(summary="", facts_json={})
        try:
            async with mvp_database() as db:
                memory = ChatMemoryService(db)
                await memory.get_or_create_conversation(identity)
                await memory.append_message(identity, "user", "LEGACY_BUSINESS sells boats")
            a = await context.switch(actor, actor, 0)
            async def talk(version, text):
                async with mvp_database() as db:
                    memory = ChatMemoryService(db)
                    scope = await memory.resolve_scope(identity, version)
                    service = ChatService(db, memory_service=memory,
                        context_service=SimpleNamespace(update_context=summarize),
                        response_service=SimpleNamespace(generate=generate),
                        url_service=SimpleNamespace(analyze=AsyncMock(return_value=SimpleNamespace(data=None, used_url=False, has_url_intent=False))),
                        image_service=SimpleNamespace(generate_if_requested=AsyncMock(return_value=None)),
                        brand_profile_service=SimpleNamespace(get_context_for_chat_user=AsyncMock(return_value={}), merge_context=lambda profile,facts: facts))
                    await service.handle(identity, text, memory_user_id=scope)
                    return scope
            first = await talk(a["version"], "BUSINESS_A_ONLY sells tea")
            assert "BUSINESS_A_ONLY" in json.dumps(packets[-1])
            b = await context.switch(actor, actor, a["version"])
            second = await talk(b["version"], "BUSINESS_B_ONLY sells cars")
            assert first != second
            assert "BUSINESS_A_ONLY" not in json.dumps(packets[-1])
            assert "LEGACY_BUSINESS" not in json.dumps(packets[-1])
            assert "BUSINESS_B_ONLY" in json.dumps(packets[-1])
            # New service/session instances keep using the same durable epoch.
            await talk(b["version"], "Continue this discussion")
            assert "BUSINESS_B_ONLY" in json.dumps(packets[-1])
            assert "BUSINESS_A_ONLY" not in json.dumps(packets[-1])
            async with mvp_database() as db:
                with pytest.raises(CopilotAPIError) as stale:
                    await ChatMemoryService(db).resolve_scope(identity, a["version"])
                assert stale.value.status == 409
            history = ProjectHistoryService(mvp_database)
            listing = await history.recent(actor, source_type="conversation")
            assert {item["public_id"] for item in listing["items"]} == {f"c:{a['version']}", f"c:{b['version']}"}
            restored = await history.restore(actor, f"c:{a['version']}")
            assert "BUSINESS_A_ONLY" in json.dumps(restored)
            assert "BUSINESS_B_ONLY" not in json.dumps(restored)
            assert "LEGACY_BUSINESS" not in json.dumps(restored)
            active = await context.switch(actor, actor, b["version"], f"c:{a['version']}")
            async with mvp_database() as db:
                with pytest.raises(CopilotAPIError):
                    await ChatMemoryService(db).resolve_scope(identity, active["version"])
        finally:
            async with mvp_database() as db, db.begin():
                await db.execute(delete(Message).where(Message.user_id.like(identity + "%")))
                await db.execute(delete(Conversation).where(Conversation.user_id.like(identity + "%")))
                await db.execute(delete(User).where(User.telegram_id == actor))
    asyncio.run(exercise())


def test_chat_http_replay_uses_resolved_epoch_and_skips_pipeline(mvp_database, monkeypatch, caplog):
    import httpx
    from fastapi import FastAPI
    from app.config import settings
    from app.db import get_session
    from app.models import MarketingRun
    import importlib
    chat_router = importlib.import_module("app.routers.chat_router")
    from app.services.chat_execution_service import ChatExecutionService
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "chat-test")
    calls, failing = [], [False]
    async def pipeline(**kwargs):
        calls.append(kwargs)
        if failing[0]:
            raise RuntimeError("PRIVATE_PROVIDER_INPUT")
        return {"reply": "saved", "follow_up_question": None, "actions": [], "debug": {}, "image": None}
    monkeypatch.setattr(chat_router, "ChatService", lambda *args, **kwargs: SimpleNamespace(handle=pipeline))
    monkeypatch.setattr(chat_router, "ChatExecutionService", lambda: ChatExecutionService(mvp_database))
    app = FastAPI()
    app.include_router(chat_router.router)
    async def session():
        async with mvp_database() as db:
            yield db
    app.dependency_overrides[get_session] = session
    async def exercise():
        actor = int(uuid.uuid4().hex[:12], 16)
        context = ProjectContextService(mvp_database, ProjectHistoryService(mvp_database))
        headers = {"authorization": "Bearer chat-test", "x-telegram-user-id": str(actor)}
        try:
            await context.switch(actor, actor, 0)
            payload = {"user_id": f"tg:{actor}", "text": "Question", "context_version": 1,
                "request_key": f"tg:{actor}:{actor}:1"}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                first = await client.post("/chat/message", headers=headers, json=payload)
                again = await client.post("/chat/message", headers=headers, json=payload)
                assert first.status_code == again.status_code == 200
                assert first.json() == again.json()
                assert len(calls) == 1
                assert calls[0]["user_id"] == f"tg:{actor}"
                assert calls[0]["memory_user_id"] == f"tg:{actor}:new:1"
                await context.switch(actor, actor, 1)
                stale = await client.post("/chat/message", headers=headers, json=payload)
                assert stale.status_code == 409 and len(calls) == 1
                failing[0] = True
                failed_payload = {**payload, "request_key": f"tg:{actor}:{actor}:2", "context_version": 2}
                failed = await client.post("/chat/message", headers=headers, json=failed_payload)
                replay = await client.post("/chat/message", headers=headers, json=failed_payload)
                assert failed.status_code == 500 and replay.status_code == 503
                assert len(calls) == 2
                assert "PRIVATE_PROVIDER_INPUT" not in failed.text + replay.text + caplog.text
        finally:
            async with mvp_database() as db, db.begin():
                owner = await db.scalar(select(User.id).where(User.telegram_id == actor))
                await db.execute(delete(MarketingRun).where(MarketingRun.user_id == owner))
                await db.execute(delete(User).where(User.id == owner))
    asyncio.run(exercise())


def test_first_updated_chat_uses_epoch_zero_and_preserves_legacy_archive(mvp_database):
    async def exercise():
        actor = int(uuid.uuid4().hex[:12], 16)
        identity = f"tg:{actor}"
        try:
            async with mvp_database() as db:
                memory = ChatMemoryService(db)
                await memory.get_or_create_conversation(identity)
                await memory.append_message(identity, "user", "Legacy facts")
                scope = await memory.resolve_scope(identity, 0)
                assert scope == identity + ":new:0"
                await memory.get_or_create_conversation(scope)
                await memory.append_message(scope, "user", "Independent new question")
                assert await memory.load_recent_messages(identity) == [{"role": "user", "text": "Legacy facts"}]
            async with mvp_database() as db:
                assert await ChatMemoryService(db).resolve_scope(identity, 0) == scope
            item = await ProjectHistoryService(mvp_database).get(actor, "c:0")
            assert "resume_conversation" in item["capabilities"]
            assert item["result"]["messages"][0]["text"] == "Independent new question"
        finally:
            async with mvp_database() as db, db.begin():
                await db.execute(delete(Message).where(Message.user_id.like(identity + "%")))
                await db.execute(delete(Conversation).where(Conversation.user_id.like(identity + "%")))
                await db.execute(delete(User).where(User.telegram_id == actor))
    asyncio.run(exercise())
