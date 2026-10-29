"""A redelivered Telegram update cannot move between execution lanes."""
import asyncio
import json

import pytest
from sqlalchemy import delete

from app.marketing_copilot.api_contracts import ConversationResponse, ExecuteRequest
from app.marketing_copilot.api_errors import CopilotAPIError
from app.marketing_copilot.execution_store import ExecutionStore
from app.models import MarketingRun
from app.services.chat_execution_service import ChatExecutionService
from app.services.project_context_service import ProjectContextService
from app.services.project_history_service import ProjectHistoryService
from tests.postgresql_support import mvp_database
from tests.test_project_context_postgresql import seed, cleanup


def test_redelivery_across_project_copilot_and_ordinary_chat_never_generates_again(mvp_database):
    async def exercise():
        actor, owner, sources = await seed(mvp_database)
        calls = []
        async def model(**kwargs):
            calls.append(kwargs)
            return json.dumps({"reply": "project response"})
        async def ordinary():
            return {"reply": "chat response", "actions": [], "debug": {}, "image": None, "follow_up_question": None}
        context = ProjectContextService(mvp_database, ProjectHistoryService(mvp_database), model_call=model)
        copilot, chat = ExecutionStore(mvp_database), ChatExecutionService(mvp_database)
        key = lambda mid: f"tg:{actor}:{actor}:{mid}"
        try:
            await chat.execute(actor, key(1), {"text": "original chat"}, f"tg:{actor}", ordinary)
            await context.switch(actor, actor, 0, sources[0])
            with pytest.raises(CopilotAPIError) as prior_chat:
                await context.message(actor, actor, 1, key(1), "original chat")
            assert prior_chat.value.code == "request_conflict" and not calls
            await context.message(actor, actor, 1, key(2), "original project question")
            assert len(calls) == 1
            await context.switch(actor, actor, 1)
            with pytest.raises(CopilotAPIError) as prior_project:
                await copilot.claim(owner, ExecuteRequest(request_key=key(2), message="original project question"))
            assert prior_project.value.code == "request_conflict"
            with pytest.raises(CopilotAPIError):
                await chat.execute(actor, key(2), {"text": "original project question"}, f"tg:{actor}:new:2", ordinary)
            payload = ExecuteRequest(request_key=key(3), message="original Copilot request")
            token, _ = await copilot.claim(owner, payload)
            await copilot.finish(owner, payload, token, ConversationResponse())
            # Normal delegation under the original identity remains valid.
            await chat.execute(actor, key(3), {"text": payload.message}, f"tg:{actor}:new:2", ordinary)
            await context.switch(actor, actor, 2, sources[1])
            with pytest.raises(CopilotAPIError):
                await context.message(actor, actor, 3, key(3), payload.message)
            assert len(calls) == 1
        finally:
            async with mvp_database() as db, db.begin():
                await db.execute(delete(MarketingRun).where(MarketingRun.user_id == owner))
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())


def test_simultaneous_cross_lane_admission_has_one_winner(mvp_database):
    async def exercise():
        actor, owner, sources = await seed(mvp_database)
        calls = []
        async def model(**kwargs):
            calls.append(kwargs)
            return json.dumps({"reply": "accepted project"})
        context = ProjectContextService(mvp_database, ProjectHistoryService(mvp_database), model_call=model)
        try:
            await context.switch(actor, actor, 0, sources[0])
            key = f"tg:{actor}:{actor}:1"
            results = await asyncio.gather(
                context.message(actor, actor, 1, key, "Question"),
                ExecutionStore(mvp_database).claim(owner, ExecuteRequest(request_key=key, message="Question")),
                return_exceptions=True)
            assert sum(isinstance(value, CopilotAPIError) and value.code == "request_conflict" for value in results) == 1
            assert sum(not isinstance(value, BaseException) for value in results) == 1
            assert len(calls) <= 1
        finally:
            async with mvp_database() as db, db.begin():
                await db.execute(delete(MarketingRun).where(MarketingRun.user_id == owner))
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())
