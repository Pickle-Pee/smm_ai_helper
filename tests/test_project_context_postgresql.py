"""Real durable project bindings/claims with captured fake-provider context."""
import asyncio
import json
import uuid

import pytest
from sqlalchemy import delete, select

from app.marketing_copilot.api_errors import CopilotAPIError, ProviderUnavailable
from app.models import ActiveProjectBinding, ProjectDiscussionTurn, ProjectSession, Task, User
from app.services.project_context_service import ProjectContextService
from app.services.project_history_service import ProjectHistoryService
from tests.postgresql_support import mvp_database


async def seed(sessions):
    actor = int(uuid.uuid4().hex[:12], 16)
    async with sessions() as db, db.begin():
        owner = User(telegram_id=actor)
        db.add(owner)
        await db.flush()
        tasks = [Task(user_id=owner.id, agent_type="strategy", task_description=value,
            result={"strategy": value, "recommendations": ["test assumption"]}, status="done")
            for value in ("Business_A_ONLY sells tea in Tula", "Business_B_ONLY sells cars in Perm")]
        db.add_all(tasks)
        await db.flush()
        return actor, owner.id, [f"t:{task.id}" for task in tasks]


async def cleanup(sessions, owner):
    async with sessions() as db, db.begin():
        await db.execute(delete(Task).where(Task.user_id == owner))
        await db.execute(delete(User).where(User.id == owner))


def test_switch_restart_isolation_replay_and_stale_buttons(mvp_database):
    async def exercise():
        actor, owner, sources = await seed(mvp_database)
        calls = []
        async def provider(**kwargs):
            calls.append(json.loads(kwargs["text"]))
            return json.dumps({"reply": "Saved project reply"})
        def runtime():
            return ProjectContextService(mvp_database, ProjectHistoryService(mvp_database), model_call=provider)
        try:
            service = runtime()
            assert await service.current(actor, actor) == {"version": 0, "active": None}
            a = await service.switch(actor, actor, 0, sources[0])
            assert a["version"] == 1 and a["active"]["public_id"] == sources[0]
            assert calls == []  # navigation and activation never generate
            response = await service.message(actor, actor, 1, f"tg:{actor}:{actor}:101", "What should change?")
            assert "Business_A_ONLY" in json.dumps(calls[-1])
            assert "Business_B_ONLY" not in json.dumps(calls[-1])
            # A fresh service instance sees the binding and completed answer.
            restarted = runtime()
            assert (await restarted.current(actor, actor))["active"]["public_id"] == sources[0]
            assert await restarted.message(actor, actor, 1, f"tg:{actor}:{actor}:101", "What should change?") == response
            assert len(calls) == 1
            b = await restarted.switch(actor, actor, 1, sources[1])
            assert b["version"] == 2
            await runtime().message(actor, actor, 2, f"tg:{actor}:{actor}:102", "What is the business?")
            assert "Business_B_ONLY" in json.dumps(calls[-1])
            assert "Business_A_ONLY" not in json.dumps(calls[-1])
            with pytest.raises(CopilotAPIError) as stale:
                await runtime().switch(actor, actor, 1, sources[0])
            assert stale.value.status == 409
            with pytest.raises(CopilotAPIError):
                await runtime().message(actor, actor, 1, f"tg:{actor}:{actor}:101", "What should change?")
            a2 = await runtime().switch(actor, actor, 2, sources[0])
            await runtime().message(actor, actor, a2["version"], f"tg:{actor}:{actor}:103", "Please recall our discussion")
            assert calls[-1]["dialogue"] == [{"question": "What should change?", "reply": "Saved project reply"}]
            assert "Business_B_ONLY" not in json.dumps(calls[-1])
            off = await runtime().switch(actor, actor, 3, None)
            assert off == {"version": 4, "active": None, "restored_components": []}
            assert len((await runtime().discussion(actor, sources[0]))["turns"]) == 2
            with pytest.raises(CopilotAPIError):
                await runtime().switch(actor, actor, 0, sources[0])
        finally:
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())


def test_owner_private_chat_and_atomic_competing_switches(mvp_database):
    async def exercise():
        actor, owner, sources = await seed(mvp_database)
        async def forbidden(**kwargs):
            pytest.fail("navigation called provider")
        service = ProjectContextService(mvp_database, ProjectHistoryService(mvp_database), model_call=forbidden)
        try:
            with pytest.raises(CopilotAPIError) as foreign:
                await service.switch(actor + 1, actor + 1, 0, sources[0])
            assert foreign.value.status == 404
            with pytest.raises(CopilotAPIError):
                await service.switch(actor, actor + 1, 0, sources[0])
            results = await asyncio.gather(service.switch(actor, actor, 0, sources[0]),
                service.switch(actor, actor, 0, sources[1]), return_exceptions=True)
            assert sum(isinstance(item, dict) for item in results) == 1
            assert sum(isinstance(item, CopilotAPIError) and item.status == 409 for item in results) == 1
            current = await service.current(actor, actor)
            assert current["version"] == 1 and current["active"]["public_id"] in sources
        finally:
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())


def test_unknown_outcome_duplicate_never_reissues_provider(mvp_database):
    async def exercise():
        actor, owner, sources = await seed(mvp_database)
        calls = []
        async def provider(**kwargs):
            calls.append(kwargs)
            raise TimeoutError("ambiguous")
        def runtime():
            return ProjectContextService(mvp_database, ProjectHistoryService(mvp_database), model_call=provider)
        try:
            await runtime().switch(actor, actor, 0, sources[0])
            key = f"tg:{actor}:{actor}:200"
            with pytest.raises(ProviderUnavailable):
                await runtime().message(actor, actor, 1, key, "Continue")
            with pytest.raises(ProviderUnavailable):
                await runtime().message(actor, actor, 1, key, "Continue")
            assert len(calls) == 1
            async with mvp_database() as db:
                status = await db.scalar(select(ProjectDiscussionTurn.status).where(ProjectDiscussionTurn.actor_id == actor))
                assert status == "unknown"
            with pytest.raises(CopilotAPIError) as changed:
                await runtime().message(actor, actor, 1, key, "Changed")
            assert changed.value.code == "request_conflict"
        finally:
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())


def test_duplicate_admission_and_switch_during_accepted_request(mvp_database):
    async def exercise():
        actor, owner, sources = await seed(mvp_database)
        accepted, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def provider(**kwargs):
            calls.append(json.loads(kwargs["text"]))
            accepted.set()
            await release.wait()
            return json.dumps({"reply": "A completed once"})
        def runtime():
            return ProjectContextService(mvp_database, ProjectHistoryService(mvp_database), model_call=provider)
        task = None
        try:
            await runtime().switch(actor, actor, 0, sources[0])
            key = f"tg:{actor}:{actor}:300"
            task = asyncio.create_task(runtime().message(actor, actor, 1, key, "Discuss A"))
            await asyncio.wait_for(accepted.wait(), timeout=10)
            # Duplicate accepted update cannot create a second provider request.
            with pytest.raises(ProviderUnavailable):
                await runtime().message(actor, actor, 1, key, "Discuss A")
            with pytest.raises(CopilotAPIError) as busy:
                await runtime().message(actor, actor, 1, f"tg:{actor}:{actor}:301", "Another question")
            assert busy.value.code == "discussion_busy"
            await runtime().switch(actor, actor, 1, sources[1])
            release.set()
            answer = await asyncio.wait_for(task, timeout=10)
            assert answer["public_id"] == sources[0]
            assert len(calls) == 1
            assert (await runtime().current(actor, actor))["active"]["public_id"] == sources[1]
            back = await runtime().switch(actor, actor, 2, sources[0])
            assert "история обсуждения" in back["restored_components"]
            assert (await runtime().discussion(actor, sources[0]))["turns"] == [
                {"question": "Discuss A", "reply": "A completed once"}]
        finally:
            release.set()
            if task is not None:
                await asyncio.gather(task, return_exceptions=True)
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())


def test_missing_source_binding_can_be_cleared(mvp_database):
    async def exercise():
        actor, owner, sources = await seed(mvp_database)
        service = ProjectContextService(mvp_database, ProjectHistoryService(mvp_database))
        try:
            await service.switch(actor, actor, 0, sources[0])
            async with mvp_database() as db, db.begin():
                await db.execute(delete(Task).where(Task.id == int(sources[0][2:])))
            state = await service.current(actor, actor)
            assert state["version"] == 1 and state["active"]["unavailable"] is True
            cleared = await service.switch(actor, actor, 1, None)
            assert cleared["active"] is None and cleared["version"] == 2
        finally:
            await cleanup(mvp_database, owner)
    asyncio.run(exercise())
