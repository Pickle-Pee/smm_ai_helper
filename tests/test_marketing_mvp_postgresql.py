import asyncio
import json
import os
import subprocess
import sys
import uuid
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Job, JobExecution, MarketingArtifact, MarketingRun, WorkflowDelivery
from app.routers import images_router
from app.routers import workflows as api
from app.worker import MarketingWorker
from app.workflows.delivery import DeliveryService
from app.workflows.executors import MarketingExecutors
from app.workflows.presentation import delivery_parts
from app.workflows.schemas import BusinessInput, StartRequest
from app.workflows.service import MarketingWorkflowService, WorkflowError, utcnow
from bot.backend import actor_headers
from bot.delivery import deliver_once
from tests.postgresql_support import mvp_database
from tests.workflow_fakes import FakeAnalyzer, FakeImages, FakeModel


def actor_id(): return int(uuid.uuid4().hex[:12], 16)


def request(**kwargs):
    return StartRequest(request_key="test-" + uuid.uuid4().hex, competitor_url="https://example.com",
                        product="Курс фотографии", audience="Начинающие фотографы", goal="Заявки на курс", **kwargs)


@pytest.fixture
def setup_mvp(mvp_database, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "IMAGE_STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "BOT_BACKEND_TOKEN", "test-mvp-secret")
    monkeypatch.setattr(settings, "API_BASE_URL", "http://test")
    service = MarketingWorkflowService(mvp_database)
    delivery = DeliveryService(mvp_database)
    model, images = FakeModel(), FakeImages()
    executors = MarketingExecutors(model_call=model, analyzer=FakeAnalyzer(), images=images)
    worker = MarketingWorker(service, executors)
    monkeypatch.setattr(api, "workflow", service)
    monkeypatch.setattr(api, "delivery", delivery)
    app = FastAPI()
    for router in (api.router, api.delivery_router, images_router): app.include_router(router)
    # Workers/delivery intentionally scan the DB; isolate persisted queues between tests.
    async def cleanup():
        async with mvp_database() as session, session.begin():
            await session.execute(delete(MarketingRun).where(MarketingRun.workflow_type == "marketing_mvp.v1"))
    asyncio.run(cleanup())  # mvp_database refuses any non-disposable database.
    yield SimpleNamespace(service=service, delivery=delivery, model=model, images=images,
                          executors=executors, worker=worker, app=app, sessions=mvp_database)
    asyncio.run(cleanup())


def test_http_to_worker_three_steps_and_durable_telegram_delivery(setup_mvp):
    ctx = setup_mvp
    async def run():
        actor = actor_id()
        headers = actor_headers(actor)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ctx.app), base_url="http://test") as client:
            payload = request().model_dump()
            accepted = await client.post("/workflows", headers=headers, json=payload)
            assert accepted.status_code == 202
            run_id = accepted.json()["run_id"]
            assert ctx.model.calls == []  # Ingress only persists, no generation.
            assert (await client.post("/workflows", headers=headers, json=payload)).json()["run_id"] == run_id
            assert await ctx.worker.once(accepted.json()["jobs"][0]["job_id"])
            first = await ctx.service.status(actor, run_id)
            assert first["status"] == "awaiting_creative" and len(ctx.model.calls) == 1
            # Survive process restart; continuation needs no original input.
            ctx.service = MarketingWorkflowService(ctx.sessions)
            await ctx.service.set_profile(actor, {"product_description": "Changed product", "audience": "Changed audience"})
            await ctx.service.continue_run(actor, run_id, "creative")
            await ctx.service.continue_run(actor, run_id, "creative")
            assert await ctx.worker.once()
            creative = await ctx.service.status(actor, run_id)
            assert creative["status"] == "awaiting_mentor"
            assert len(ctx.model.calls) == 2 and len(ctx.images.calls) == 1
            assert len(creative["jobs"]) == 2  # Mentor was not scheduled automatically.
            image_url = creative["artifacts"]["creative"]["images"][0]["url"]
            assert (await client.get(image_url, headers=headers)).status_code == 200
            assert (await client.get(image_url, headers=actor_headers(actor + 1))).status_code == 404
            await ctx.service.continue_run(actor, run_id, "mentor")
            assert await ctx.worker.once()
            final = await ctx.service.status(actor, run_id)
            assert final["status"] == "completed"
            assert set(final["artifacts"]) == {"analysis", "creative", "mentor"}
            mentor = final["artifacts"]["mentor"]
            assert mentor["input"]["snapshot"]["product"] == "Курс фотографии"
            assert mentor["lineage"] and mentor["quality_gate"]["synthesis_manifest"]["accepted_result_ids"]
            for path in (f"/workflows/{run_id}", f"/workflows/{run_id}/artifacts/creative", f"/workflows/{run_id}/jobs/{final['jobs'][0]['job_id']}"):
                assert (await client.get(path, headers=actor_headers(actor + 1))).status_code == 404
                assert (await client.get(path)).status_code == 401
            assert (await client.post(f"/workflows/{run_id}/continue", headers=actor_headers(actor + 1), json={"action": "mentor"})).status_code == 404
            bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=1001)),
                                  send_photo=AsyncMock(return_value=SimpleNamespace(message_id=1002)))
            for _ in range(30):
                if not await deliver_once(bot, client): break
            delivered = await ctx.service.status(actor, run_id)
            assert all(d["status"] == "delivered" for d in delivered["delivery"])
            assert bot.send_photo.call_count == 1
            assert all(call.args[0] == actor for call in bot.send_message.call_args_list)
            count = len(ctx.model.calls)
            await ctx.service.continue_run(actor, run_id, "mentor")
            assert not await ctx.worker.once(final["jobs"][-1]["job_id"])
            assert len(ctx.model.calls) == count
    asyncio.run(run())


def test_missing_context_is_durable_and_same_key_conflict_is_rejected(setup_mvp):
    ctx = setup_mvp
    async def run():
        actor = actor_id()
        req = StartRequest(request_key="test-message-1", competitor_url="https://example.com")
        result = await ctx.service.start(actor, req)
        assert result["status"] == "needs_input" and not result["jobs"]
        restarted = MarketingWorkflowService(ctx.sessions)
        result = await restarted.context(actor, result["run_id"], BusinessInput(product="Курс", audience="Студенты", goal="Заявки"))
        assert result["status"] == "queued" and len(result["jobs"]) == 1
        with pytest.raises(WorkflowError):
            await restarted.start(actor, req.model_copy(update={"competitor_url": "https://other.example"}))
    asyncio.run(run())


def test_competing_requests_and_claims_have_one_winner(setup_mvp):
    ctx = setup_mvp
    async def run():
        actor, req = actor_id(), request()
        first, second = await asyncio.gather(ctx.service.start(actor, req), ctx.service.start(actor, req))
        assert first["run_id"] == second["run_id"]
        job_id = first["jobs"][0]["job_id"]
        claims = await asyncio.gather(ctx.service.claim(job_id), ctx.service.claim(job_id))
        assert sum(c is not None for c in claims) == 1
        item = next(c for c in claims if c)
        artifact = await ctx.executors.execute(item)
        assert await ctx.service.finish(item, artifact, delivery_parts(artifact))
        assert not await ctx.service.finish(item, artifact, delivery_parts(artifact))
        async with ctx.sessions() as session:
            assert await session.scalar(select(func.count()).select_from(MarketingArtifact).where(MarketingArtifact.run_id == item.run_id)) == 1
    asyncio.run(run())


def test_commit_publication_crash_redis_loss_and_expired_worker_are_recoverable(setup_mvp):
    ctx = setup_mvp
    async def run():
        actor, req = actor_id(), request()
        broken_queue = SimpleNamespace(wake=AsyncMock(side_effect=ConnectionError("lost Redis")))
        producer = MarketingWorkflowService(ctx.sessions, queue=broken_queue)
        with pytest.raises(ConnectionError): await producer.start(actor, req)
        saved = await ctx.service.start(actor, req)
        job_id = saved["jobs"][0]["job_id"]
        stale = await ctx.service.claim(job_id)
        async with ctx.sessions() as session, session.begin():
            await session.execute(update(JobExecution).where(JobExecution.job_id == job_id).values(lease_until=utcnow() - timedelta(seconds=1)))
        resumed = await MarketingWorkflowService(ctx.sessions).claim(job_id)
        assert resumed.token != stale.token
        artifact = await ctx.executors.execute(resumed)
        assert not await ctx.service.finish(stale, artifact, delivery_parts(artifact))
        assert await ctx.service.finish(resumed, artifact, delivery_parts(artifact))
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["url", "malformed", "timeout"])
def test_failures_are_bounded_and_visible(setup_mvp, failure):
    ctx = setup_mvp
    async def run():
        actor = actor_id()
        saved = await ctx.service.start(actor, request())
        job_id = saved["jobs"][0]["job_id"]
        if failure == "url": ctx.executors.analyzer.analyze = AsyncMock(return_value=None)
        elif failure == "malformed": ctx.executors.model_call = AsyncMock(return_value=("{}", {}))
        else: ctx.executors.model_call = AsyncMock(side_effect=TimeoutError())
        for _ in range(3):
            await ctx.worker.once(job_id)
            async with ctx.sessions() as session, session.begin():
                await session.execute(update(JobExecution).where(JobExecution.job_id == job_id).values(available_at=utcnow()))
        result = await ctx.service.status(actor, saved["run_id"])
        assert result["status"] == "failed" and result["error"]
        assert not result["artifacts"] and result["delivery"]
        async with ctx.sessions() as session:
            lease = await session.get(JobExecution, job_id)
            assert lease.attempts == (3 if failure == "timeout" else 1)
    asyncio.run(run())


def test_result_commit_failure_rolls_back_job_artifact_and_delivery_together(setup_mvp):
    ctx = setup_mvp
    async def run():
        actor = actor_id()
        saved = await ctx.service.start(actor, request())
        job_id = saved["jobs"][0]["job_id"]
        item = await ctx.service.claim(job_id)
        artifact = await ctx.executors.execute(item)
        def reject_commit(session):
            raise SQLAlchemyError("injected commit failure")
        event.listen(Session, "before_commit", reject_commit)
        try:
            with pytest.raises(SQLAlchemyError):
                await ctx.service.finish(item, artifact, delivery_parts(artifact))
        finally:
            event.remove(Session, "before_commit", reject_commit)
        result = await ctx.service.status(actor, saved["run_id"])
        assert result["status"] == "running" and not result["artifacts"] and not result["delivery"]
        assert result["jobs"][0]["status"] == "running"
        # The same live attempt can retry persistence without another model call.
        assert await ctx.service.finish(item, artifact, delivery_parts(artifact))
        assert len(ctx.model.calls) == 1
        assert not await ctx.service.finish(item, artifact, delivery_parts(artifact))
    asyncio.run(run())


def test_delivery_retry_restart_and_fencing_do_not_generate_again(setup_mvp):
    ctx = setup_mvp
    async def run():
        actor = actor_id()
        saved = await ctx.service.start(actor, request())
        item = await ctx.service.claim(saved["jobs"][0]["job_id"])
        artifact = await ctx.executors.execute(item)
        await ctx.service.finish(item, artifact, [{"kind": "text", "text": "first"}, {"kind": "text", "text": "second"}])
        a, b = await asyncio.gather(ctx.delivery.claim(), ctx.delivery.claim())
        assert sum(x is not None for x in (a, b)) == 1  # Part 2 waits for part 1.
        stale = a or b
        async with ctx.sessions() as session, session.begin():
            await session.execute(update(WorkflowDelivery).where(WorkflowDelivery.delivery_id == stale["delivery_id"])
                                  .values(lease_until=utcnow() - timedelta(seconds=1)))
        restarted = DeliveryService(ctx.sessions)
        claim = await restarted.claim()
        assert claim["delivery_id"] == stale["delivery_id"] and claim["claim_token"] != stale["claim_token"]
        assert not await restarted.acknowledge(stale["delivery_id"], stale["claim_token"], message_id=11)
        assert await restarted.acknowledge(claim["delivery_id"], claim["claim_token"], retryable=False)
        assert await restarted.claim() is None  # Terminal part failure doesn't skip data.
        with pytest.raises(WorkflowError): await ctx.service.retry_delivery(actor + 1, saved["run_id"])
        await ctx.service.retry_delivery(actor, saved["run_id"])
        claim = await restarted.claim()
        assert await restarted.acknowledge(claim["delivery_id"], claim["claim_token"], retry_after=120)
        assert await restarted.claim() is None
        async with ctx.sessions() as session, session.begin():
            await session.execute(update(WorkflowDelivery).values(available_at=utcnow()))
        for text in ("first", "second"):
            claim = await restarted.claim()
            assert claim["payload"]["text"] == text
            assert await restarted.acknowledge(claim["delivery_id"], claim["claim_token"], message_id=12)
        assert await restarted.claim() is None
        assert len(ctx.model.calls) == 1
        assert all(d["status"] == "delivered" for d in (await ctx.service.status(actor, saved["run_id"]))["delivery"])
    asyncio.run(run())


def test_crashing_workers_exhaust_bounded_attempts(setup_mvp):
    ctx = setup_mvp
    async def run():
        actor = actor_id()
        saved = await ctx.service.start(actor, request())
        job_id = saved["jobs"][0]["job_id"]
        for _ in range(3):
            assert await ctx.service.claim(job_id)
            async with ctx.sessions() as session, session.begin():
                await session.execute(update(JobExecution).where(JobExecution.job_id == job_id)
                                      .values(lease_until=utcnow() - timedelta(seconds=1)))
        assert await ctx.service.claim(job_id) is None
        final = await ctx.service.status(actor, saved["run_id"])
        assert final["status"] == "failed" and len(final["delivery"]) == 1
        assert ctx.model.calls == []
    asyncio.run(run())


def test_wrapped_provider_outage_is_retried_and_db_transactions_are_closed(setup_mvp):
    ctx = setup_mvp
    async def run():
        actor = actor_id()
        saved = await ctx.service.start(actor, request())
        job_id = saved["jobs"][0]["job_id"]
        async def fail(**kwargs):
            # A distinct connection can lock both records while provider work runs.
            async with ctx.sessions() as session, session.begin():
                await session.scalar(select(JobExecution).where(JobExecution.job_id == job_id).with_for_update(nowait=True))
                await session.scalar(select(MarketingRun).where(MarketingRun.run_id == saved["run_id"]).with_for_update(nowait=True))
            try: raise httpx.ConnectError("injected outage")
            except httpx.ConnectError as exc: raise RuntimeError("provider adapter exhausted") from exc
        ctx.executors.model_call = fail
        assert await ctx.worker.once(job_id)
        final = await ctx.service.status(actor, saved["run_id"])
        assert final["status"] == "queued" and not final["delivery"]
    asyncio.run(run())


def test_internal_delivery_api_fails_closed(setup_mvp):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=setup_mvp.app), base_url="http://test") as client:
            assert (await client.post("/internal/delivery/claim")).status_code == 401
            assert (await client.post("/internal/delivery/claim", headers={"X-Telegram-User-ID": "123"})).status_code == 401
            assert (await client.post("/internal/delivery/claim", headers={"Authorization": "Bearer test-mvp-secret"})).json() is None
    asyncio.run(run())


def test_separate_worker_process_crash_and_restart(setup_mvp):
    ctx = setup_mvp
    child = """
import asyncio, os, sys
from app.workflows.service import MarketingWorkflowService
from app.workflows.executors import MarketingExecutors
from app.worker import MarketingWorker
from tests.workflow_fakes import FakeAnalyzer, FakeImages, FakeModel
async def main():
    service = MarketingWorkflowService()
    if sys.argv[1] == 'crash':
        assert await service.claim(sys.argv[2])
        os._exit(0)  # Abruptly stop after the claim commit, before execution.
    worker = MarketingWorker(service, MarketingExecutors(model_call=FakeModel(), analyzer=FakeAnalyzer(), images=FakeImages()))
    assert await worker.once(sys.argv[2])
asyncio.run(main())
"""
    async def run():
        actor = actor_id()
        saved = await ctx.service.start(actor, request())
        job_id = saved["jobs"][0]["job_id"]
        env = {**os.environ, "DATABASE_URL": os.environ["MVP_TEST_DATABASE_URL"],
               "OPENAI_API_KEY": "offline-test-key", "IMAGE_STORAGE_PATH": settings.IMAGE_STORAGE_PATH}
        def process(mode, job):
            result = subprocess.run([sys.executable, "-c", child, mode, job], env=env, capture_output=True, text=True, timeout=30)
            assert result.returncode == 0, result.stderr
        await asyncio.to_thread(process, "crash", job_id)
        assert not await ctx.worker.once(job_id)  # Live lease remains owned by the stopped process.
        async with ctx.sessions() as session, session.begin():
            await session.execute(update(JobExecution).where(JobExecution.job_id == job_id).values(lease_until=utcnow() - timedelta(seconds=1)))
        await asyncio.to_thread(process, "execute", job_id)
        analysis = await ctx.service.status(actor, saved["run_id"])
        assert analysis["status"] == "awaiting_creative"
        creative = await ctx.service.continue_run(actor, saved["run_id"], "creative")
        await asyncio.to_thread(process, "execute", creative["jobs"][-1]["job_id"])
        assert (await ctx.service.status(actor, saved["run_id"]))["status"] == "awaiting_mentor"
        assert ctx.model.calls == []  # Both steps actually executed outside the test process.
    asyncio.run(run())
