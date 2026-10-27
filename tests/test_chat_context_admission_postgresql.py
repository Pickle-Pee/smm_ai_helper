"""Controlled resolve/admission races against real PostgreSQL; no external I/O."""
import asyncio
import importlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, select

from app.config import settings
from app.db import get_session
from app.models import MarketingRun
from app.services.chat_execution_service import ChatExecutionService
from app.services.project_context_service import ProjectContextService
from app.services.project_history_service import ProjectHistoryService
from tests.postgresql_support import mvp_database
from tests.test_project_context_postgresql import seed, cleanup


@pytest.mark.parametrize("transition", ["activate", "deactivate", "new"])
def test_resolved_chat_cannot_be_admitted_after_context_change(mvp_database, monkeypatch, transition):
    router = importlib.import_module("app.routers.chat_router")
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "offline-race")

    async def exercise():
        actor, owner, sources = await seed(mvp_database)
        context = ProjectContextService(mvp_database, ProjectHistoryService(mvp_database))
        resolved, release = asyncio.Event(), asyncio.Event()
        calls = []
        class PausedAdmission(ChatExecutionService):
            async def _claim(self, *args, **kwargs):
                resolved.set()
                await asyncio.wait_for(release.wait(), 10)
                return await super()._claim(*args, **kwargs)
        async def pipeline(**kwargs):
            calls.append(kwargs)
            return {"reply": "should never generate", "follow_up_question": None, "actions": [], "debug": {}, "image": None}
        monkeypatch.setattr(router, "ChatService", lambda *a, **kw: SimpleNamespace(handle=pipeline))
        monkeypatch.setattr(router, "ChatExecutionService", lambda: PausedAdmission(mvp_database))
        app = FastAPI()
        app.include_router(router.router)
        async def session():
            async with mvp_database() as db:
                yield db
        app.dependency_overrides[get_session] = session
        task = None
        key = f"tg:{actor}:{actor}:901"
        try:
            # Starts with no project and explicit epoch zero. Pause after the
            # router's resolve_scope/rollback, before durable admission.
            payload = {"user_id": f"tg:{actor}", "text": "original update", "context_version": 0, "request_key": key}
            headers = {"authorization": "Bearer offline-race", "x-telegram-user-id": str(actor)}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                task = asyncio.create_task(client.post("/chat/message", headers=headers, json=payload))
                await asyncio.wait_for(resolved.wait(), 10)
                if transition == "new":
                    await context.switch(actor, actor, 0)
                else:
                    await context.switch(actor, actor, 0, sources[0])
                    if transition == "deactivate":
                        await context.switch(actor, actor, 1)
                release.set()
                result = await asyncio.wait_for(task, 10)
                assert result.status_code == 409, result.text
                assert result.json()["detail"] == "stale_context"
                # Redelivery of the exact Telegram identity stays rejected.
                repeated = await client.post("/chat/message", headers=headers, json=payload)
                assert repeated.status_code == 409
                assert calls == []
                async with mvp_database() as db:
                    assert await db.get(MarketingRun, ChatExecutionService.identity(actor, key)) is None
        finally:
            release.set()
            if task:
                await asyncio.gather(task, return_exceptions=True)
            async with mvp_database() as db, db.begin():
                await db.execute(delete(MarketingRun).where(MarketingRun.user_id == owner))
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())



def test_ordinary_chat_and_copilot_race_share_one_telegram_identity(mvp_database):
    from app.marketing_copilot.api_contracts import ExecuteRequest
    from app.marketing_copilot.api_errors import CopilotAPIError
    from app.marketing_copilot.execution_store import ExecutionStore

    async def exercise():
        actor, owner, sources = await seed(mvp_database)
        calls = []
        key = f"tg:{actor}:{actor}:902"
        async def operation():
            calls.append(key)
            async with mvp_database() as db:
                assert (await db.get(MarketingRun, ChatExecutionService.identity(actor, key))).status == "running"
            return {"reply": "once", "follow_up_question": None, "actions": [], "debug": {}, "image": None}
        try:
            results = await asyncio.wait_for(asyncio.gather(
                ChatExecutionService(mvp_database).execute(actor, key, {"text": "question"}, f"tg:{actor}", operation),
                ExecutionStore(mvp_database, wait_seconds=0).claim(owner, ExecuteRequest(request_key=key, message="question")),
                return_exceptions=True), 10)
            assert sum(not isinstance(result, BaseException) for result in results) == 1
            assert sum(isinstance(result, CopilotAPIError) and result.code == "request_conflict" for result in results) == 1
            assert len(calls) <= 1
        finally:
            async with mvp_database() as db, db.begin():
                await db.execute(delete(MarketingRun).where(MarketingRun.user_id == owner))
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())


def test_admitted_chat_releases_context_locks_before_provider(mvp_database):
    async def exercise():
        actor, owner, sources = await seed(mvp_database)
        context = ProjectContextService(mvp_database, ProjectHistoryService(mvp_database))
        accepted, release = asyncio.Event(), asyncio.Event()
        calls = []
        key = f"tg:{actor}:{actor}:903"
        async def operation():
            calls.append(key)
            accepted.set()
            await asyncio.wait_for(release.wait(), 10)
            return {"reply": "original context", "follow_up_question": None, "actions": [], "debug": {}, "image": None}
        task = None
        try:
            task = asyncio.create_task(ChatExecutionService(mvp_database).execute(
                actor, key, {"text": "question"}, f"tg:{actor}", operation))
            await asyncio.wait_for(accepted.wait(), 10)
            # Switch must commit while external work is paused, not wait on a
            # transaction spanning the model call. The accepted scope stays A.
            selected = await asyncio.wait_for(context.switch(actor, actor, 0, sources[0]), 5)
            assert selected["version"] == 1
            release.set()
            assert (await asyncio.wait_for(task, 10))["reply"] == "original context"
            assert calls == [key]
        finally:
            release.set()
            if task:
                await asyncio.gather(task, return_exceptions=True)
            async with mvp_database() as db, db.begin():
                await db.execute(delete(MarketingRun).where(MarketingRun.user_id == owner))
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())
