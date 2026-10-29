"""Durable chat update replay and fail-closed outcomes against PostgreSQL."""
import asyncio
from datetime import datetime, timedelta
import uuid

import pytest
from sqlalchemy import delete, select

from app.marketing_copilot.api_errors import CopilotAPIError, ProviderUnavailable
from app.models import MarketingRun, User
from app.services.chat_execution_service import ChatExecutionService, WORKFLOW_TYPE
from tests.postgresql_support import mvp_database


def response(text="saved"):
    return {"reply": text, "follow_up_question": None, "actions": [], "debug": {}, "image": None}


async def cleanup(sessions, actor):
    async with sessions() as db, db.begin():
        owner = await db.scalar(select(User.id).where(User.telegram_id == actor))
        await db.execute(delete(MarketingRun).where(MarketingRun.user_id == owner, MarketingRun.workflow_type == WORKFLOW_TYPE))
        await db.execute(delete(User).where(User.id == owner))


def test_chat_restarts_replay_and_changed_payload_scope_conflict(mvp_database):
    async def exercise():
        actor = int(uuid.uuid4().hex[:12], 16)
        key, scope = f"tg:{actor}:{actor}:1", f"tg:{actor}:new:1"
        payload = {"user_id": f"tg:{actor}", "text": "Discuss project A", "attachments": [], "context_version": 1}
        calls = []
        async def operation():
            calls.append("generation")
            # Claim must be committed and independently visible before provider.
            async with mvp_database() as db:
                record = await db.get(MarketingRun, ChatExecutionService.identity(actor, key))
                assert record.status == "running"
            return response()
        try:
            from app.services.project_context_service import ProjectContextService
            from app.services.project_history_service import ProjectHistoryService
            await ProjectContextService(mvp_database, ProjectHistoryService(mvp_database)).switch(actor, actor, 0)
            first = await ChatExecutionService(mvp_database).execute(actor, key, payload, scope, operation)
            replay = await ChatExecutionService(mvp_database).execute(actor, key, payload, scope, operation)
            assert replay == first == response()
            assert len(calls) == 1
            for changed, memory in (({**payload, "text": "changed"}, scope), (payload, f"tg:{actor}:new:2")):
                with pytest.raises(CopilotAPIError) as conflict:
                    await ChatExecutionService(mvp_database).execute(actor, key, changed, memory, operation)
                assert conflict.value.status == 409
            # Neither current-context epoch nor altered text can steal an identity.
            assert len(calls) == 1
        finally:
            await cleanup(mvp_database, actor)
    asyncio.run(exercise())


def test_chat_concurrent_delivery_only_one_external_operation(mvp_database):
    async def exercise():
        actor = int(uuid.uuid4().hex[:12], 16)
        key, scope = f"tg:{actor}:{actor}:2", f"tg:{actor}"
        payload = {"user_id": scope, "text": "question"}
        accepted, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def operation():
            calls.append("call")
            accepted.set()
            await release.wait()
            return response()
        task = None
        try:
            task = asyncio.create_task(ChatExecutionService(mvp_database).execute(actor, key, payload, scope, operation))
            await asyncio.wait_for(accepted.wait(), timeout=10)
            with pytest.raises(ProviderUnavailable):
                await ChatExecutionService(mvp_database).execute(actor, key, payload, scope, operation)
            assert len(calls) == 1
            release.set()
            assert await task == response()
            assert await ChatExecutionService(mvp_database).execute(actor, key, payload, scope, operation) == response()
            assert len(calls) == 1
        finally:
            release.set()
            if task:
                await asyncio.gather(task, return_exceptions=True)
            await cleanup(mvp_database, actor)
    asyncio.run(exercise())


def test_chat_unknown_and_expired_identity_never_reexecute(mvp_database):
    async def exercise():
        actor = int(uuid.uuid4().hex[:12], 16)
        key, scope = f"tg:{actor}:{actor}:3", f"tg:{actor}"
        payload, calls = {"user_id": scope, "text": "question"}, []
        async def operation():
            calls.append("unknown")
            raise TimeoutError("unknown")
        try:
            for _ in range(2):
                with pytest.raises(ProviderUnavailable):
                    await ChatExecutionService(mvp_database).execute(actor, key, payload, scope, operation)
            assert len(calls) == 1
            async with mvp_database() as db, db.begin():
                row = await db.get(MarketingRun, ChatExecutionService.identity(actor, key))
                assert row.status == "ambiguous"
                row.created_at = datetime.utcnow() - timedelta(days=31)
            with pytest.raises(CopilotAPIError) as expired:
                await ChatExecutionService(mvp_database).execute(actor, key, payload, scope, operation)
            assert expired.value.status == 404
            assert len(calls) == 1
        finally:
            await cleanup(mvp_database, actor)
    asyncio.run(exercise())


@pytest.mark.parametrize("actor,key,scope", [
    (True, "tg:1:1:1", "tg:1"),
    (123, "tg:124:124:1", "tg:123"),
    (123, "tg:123:124:1", "tg:123"),
    (123, "tg:123:123:0", "tg:123"),
    (123, "tg:123:123:1", "tg:124:new:1"),
    (123, "tg:123:123:action:bad", "tg:123"),
])
def test_chat_update_identity_rejected_before_persistence(actor, key, scope):
    def forbidden():
        pytest.fail("invalid identity reached persistence")
    async def operation():
        pytest.fail("invalid identity reached provider")
    async def exercise():
        with pytest.raises(CopilotAPIError) as failure:
            await ChatExecutionService(forbidden).execute(actor, key, {"text": "question"}, scope, operation)
        assert failure.value.status == 422
    asyncio.run(exercise())
