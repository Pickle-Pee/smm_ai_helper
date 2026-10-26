"""History projection over real PostgreSQL, with external integrations faked."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import delete

from app.marketing_copilot.api_errors import CopilotAPIError
from app.models import (Conversation, MarketingArtifact, MarketingRun, Message, ProjectSession,
                        Task, User)
from app.services.project_history_service import ProjectHistoryService
from app.workflows.executors import MarketingExecutors
from app.workflows.service import WorkItem
from tests.postgresql_support import mvp_database
from tests.workflow_fakes import FakeAnalyzer, FakeImages, FakeModel


def test_projection_unifies_sources_deduplicates_and_preserves_readonly_context(mvp_database):
    async def exercise():
        actor = int(uuid.uuid4().hex[:12], 16)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        graph_id, workflow_id, receipt_id, duplicate_id, companion_id, expired_id = (
            uuid.uuid4().hex * 2, uuid.uuid4().hex, uuid.uuid4().hex * 2,
            uuid.uuid4().hex * 2, uuid.uuid4().hex * 2, uuid.uuid4().hex * 2)
        async with mvp_database() as db, db.begin():
            user = User(telegram_id=actor)
            db.add(user)
            await db.flush()
            owner = user.id
            tasks = [Task(user_id=owner, agent_type="strategy", task_description=f"Business_{i}",
                result={"strategy": f"Business_{i} generated recommendation"}, status="done", created_at=now - timedelta(days=3))
                for i in range(7)]
            db.add_all(tasks)
            db.add_all([
                MarketingRun(run_id=graph_id, user_id=owner, workflow_type="orchestration_graph.v1", status="running",
                    input_json={"history_title":"Graph business"}, state_json={}, created_at=now, updated_at=now),
                MarketingRun(run_id=workflow_id, user_id=owner, workflow_type="marketing_mvp.v1", status="failed",
                    input_json={"product":"Workflow business","goal":"More inquiries"}, state_json={}, created_at=now, updated_at=now),
                MarketingRun(run_id=receipt_id, user_id=owner, workflow_type="copilot_execution.v1", status="completed",
                    input_json={"fingerprint":"x"}, state_json={"response":{"kind":"CONVERSATION","delegate":"legacy_chat","schema_version":"copilot_api.v1"}}, created_at=now, updated_at=now),
                MarketingRun(run_id=duplicate_id, user_id=owner, workflow_type="copilot_execution.v1", status="completed",
                    input_json={}, state_json={"response":{"kind":"WORKFLOW_STARTED","run_id":graph_id}}, created_at=now, updated_at=now),
                MarketingRun(run_id=companion_id, user_id=owner, workflow_type="case_mentor.v1", status="completed",
                    input_json={"source_run_id":graph_id}, state_json={}, created_at=now, updated_at=now),
                MarketingRun(run_id=expired_id, user_id=owner, workflow_type="copilot_execution.v1", status="completed",
                    input_json={}, state_json={}, created_at=now-timedelta(days=31), updated_at=now-timedelta(days=31)),
                Conversation(user_id=f"tg:{actor}",summary="Unsplit archive",facts_json={},updated_at=now),
                Conversation(user_id=f"tg:{actor}:new:0",summary="Business_A_ONLY",facts_json={"product":"Business_A_ONLY"},updated_at=now),
                Conversation(user_id=f"tg:{actor}:new:1",summary="Business_B_ONLY",facts_json={"product":"Business_B_ONLY"},updated_at=now),
            ])
            await db.flush()
            db.add(Message(user_id=f"tg:{actor}", role="user", text="Legacy A and B together", created_at=now))
            db.add(Message(user_id=f"tg:{actor}:new:0",role="user",text="Business_A_ONLY old conversation",created_at=now))
            db.add(Message(user_id=f"tg:{actor}:new:1",role="user",text="Business_B_ONLY old conversation",created_at=now))
            db.add(ProjectSession(session_id=uuid.uuid4().hex,owner_id=owner,public_id=f"t:{tasks[0].id}",
                source_type="task",source_id=str(tasks[0].id),title="Business_0",mode="project_chat",
                last_activity_at=datetime.now(timezone.utc)+timedelta(minutes=1)))
            task_ids = [task.id for task in tasks]
        service = ProjectHistoryService(mvp_database)
        try:
            pages, offset = [], 0
            while True:
                page = await service.recent(actor,limit=3,offset=offset)
                pages.extend(page["items"])
                if page["next_offset"] is None:
                    break
                offset = page["next_offset"]
            assert len(pages) == 13  # 7 tasks, graph, workflow, receipt, legacy, 2 independent conversations
            assert len({item["public_id"] for item in pages}) == len(pages)
            assert pages[0]["public_id"] == f"t:{task_ids[0]}"  # session activity, not original create date
            assert {item["source_type"] for item in pages} == {"task","graph","workflow","receipt","legacy","conversation"}
            assert all(companion_id not in item["public_id"] and duplicate_id not in item["public_id"] and expired_id not in item["public_id"] for item in pages)
            assert len((await service.recent(actor,status="completed"))["items"]) == 8
            assert len((await service.recent(actor,status="running"))["items"]) == 1
            assert (await service.recent(actor,source_type="workflow",status="failed"))["items"][0]["public_id"] == f"w:{workflow_id}"
            assert len((await service.recent(actor,query="Стратегия продвижения — Business_1"))["items"]) == 1
            assert (await service.recent(actor+1))["items"] == []
            for identity in (f"t:{task_ids[0]}",f"w:{workflow_id}",f"g:{graph_id}",f"r:{receipt_id}"):
                with pytest.raises(CopilotAPIError) as error:
                    await service.get(actor+1,identity)
                assert error.value.status == 404
            task = await service.get(actor,f"t:{task_ids[0]}")
            assert task["result"] == {"strategy":"Business_0 generated recommendation"}
            restored = await ProjectHistoryService(mvp_database).restore(actor,f"t:{task_ids[0]}")
            assert restored["mode"] == "project_chat"
            assert restored["context"]["user_request"] == "Business_0"
            assert "Business_1" not in str(restored)
            legacy = await service.get(actor,"l:chat")
            assert legacy["capabilities"] == ["view_result"]
            assert legacy["result"]["messages"][0]["text"] == "Legacy A and B together"
            with pytest.raises(CopilotAPIError):
                await service.restore(actor,"l:chat")
            isolated = await service.get(actor,"c:0")
            assert "Business_A_ONLY" in isolated["result"]["messages"][0]["text"]
            restored_chat = await service.restore(actor,"c:0")
            assert restored_chat["source_id"] == f"tg:{actor}:new:0"
            assert "Business_A_ONLY" in str(restored_chat) and "Business_B_ONLY" not in str(restored_chat)
            with pytest.raises(CopilotAPIError):
                await service.restore(actor+1,"c:0")
            failed = await service.get(actor,f"w:{workflow_id}")
            assert failed["status"] == "failed" and "resume_conversation" not in failed["capabilities"]
        finally:
            async with mvp_database() as db, db.begin():
                await db.execute(delete(ProjectSession).where(ProjectSession.owner_id==owner))
                await db.execute(delete(Message).where(Message.user_id.in_([f"tg:{actor}",f"tg:{actor}:new:0",f"tg:{actor}:new:1"])))
                await db.execute(delete(Conversation).where(Conversation.user_id.in_([f"tg:{actor}",f"tg:{actor}:new:0",f"tg:{actor}:new:1"])))
                await db.execute(delete(MarketingRun).where(MarketingRun.user_id==owner))
                await db.execute(delete(Task).where(Task.user_id==owner))
                await db.execute(delete(User).where(User.id==owner))
    asyncio.run(exercise())


def test_workflow_restoration_requires_accepted_typed_artifacts(mvp_database):
    async def exercise():
        actor = int(uuid.uuid4().hex[:12],16)
        rid = uuid.uuid4().hex
        snapshot={"captured_at":datetime.now(timezone.utc).isoformat(),"product":"Business_A_ONLY course", "audience":"Students", "goal":"Applications", "competitor_url":"https://example.com"}
        model=FakeModel()
        executors=MarketingExecutors(model_call=model,analyzer=FakeAnalyzer(),images=FakeImages())
        artifact=await executors.execute(WorkItem("job",rid,"analysis","token",snapshot,{}))
        assert len(model.calls)==1
        async with mvp_database() as db,db.begin():
            user=User(telegram_id=actor)
            db.add(user)
            await db.flush()
            owner=user.id
            db.add(MarketingRun(run_id=rid,user_id=owner,workflow_type="marketing_mvp.v1",status="awaiting_creative",input_json=snapshot,state_json={}))
            await db.flush()
            db.add(MarketingArtifact(run_id=rid,artifact_key="analysis",artifact_type=artifact["schema_version"],step="analysis",payload_json=artifact))
        try:
            service=ProjectHistoryService(mvp_database)
            card=await service.get(actor,"w:"+rid)
            assert "resume_conversation" in card["capabilities"]
            assert "input" not in card["result"]["analysis"]
            restored=await service.restore(actor,"w:"+rid)
            assert restored["context"]["user_business_input"]["product"]==snapshot["product"]
            assert restored["context"]["generated_results"]["analysis"]["result"]["claims"]
            assert len(model.calls)==1  # navigation/restoration read only
            # Forging a persisted accepted-id list cannot bypass revalidation.
            corrupted=dict(artifact)
            corrupted["result"]={**artifact["result"],"claims":[{**artifact["result"]["claims"][0],"evidence_ids":["foreign-evidence"]}]}
            assert ProjectHistoryService._workflow_artifacts([SimpleNamespace(payload_json=corrupted,artifact_key="analysis")],rid)=={}
        finally:
            async with mvp_database() as db,db.begin():
                await db.execute(delete(MarketingRun).where(MarketingRun.run_id==rid))
                await db.execute(delete(User).where(User.id==owner))
    asyncio.run(exercise())


def test_activity_metadata_preserves_utc_under_non_utc_database_session(mvp_database):
    from contextlib import asynccontextmanager
    from datetime import datetime
    from sqlalchemy import text
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        async with mvp_database() as db, db.begin():
            user = User(telegram_id=actor)
            db.add(user)
            await db.flush()
            owner = user.id
            task = Task(user_id=owner, agent_type="strategy", task_description="Saved UTC source",
                status="done", result={"result": "saved"}, created_at=datetime(2026, 10, 26, 12, 30))
            db.add(task)
            await db.flush()
            public_id = f"t:{task.id}"
        @asynccontextmanager
        async def non_utc_sessions():
            async with mvp_database() as db:
                await db.execute(text("SET LOCAL TIME ZONE 'Europe/Moscow'"))
                yield db
        try:
            items = (await ProjectHistoryService(non_utc_sessions).recent(actor))["items"]
            item = next(item for item in items if item["public_id"] == public_id)
            assert item["created_at"] == "2026-10-26T12:30:00+00:00"
            assert item["last_activity_at"] == item["created_at"]
        finally:
            async with mvp_database() as db, db.begin():
                await db.execute(delete(Task).where(Task.user_id == owner))
                await db.execute(delete(User).where(User.id == owner))
    asyncio.run(check())
