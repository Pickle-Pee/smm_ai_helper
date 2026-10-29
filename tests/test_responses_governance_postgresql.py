"""Real worker/PostgreSQL rollback/fencing/recovery; external calls are mocked.

Faults run inside PostgreSQL triggers, including deferred COMMIT failures and
backend termination. Never point MVP_TEST_DATABASE_URL at production.
"""
import asyncio
from contextlib import asynccontextmanager
import logging
import traceback
import uuid

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.llm.openai_text import ModelResponseError
from app.llm.telemetry import graph_call_context
from app.models import JobExecution, JobStatus, MarketingRun, WorkerAttempt
from app.module_execution import ModuleExecutorDispatcher
from app.orchestration_runtime.contracts import GraphWorkItem, module_job_id
from app.orchestration_runtime.model_adapter import production_model_call
from app.orchestration_runtime.retry_policy import RetryGovernanceError
from app.orchestration_runtime.service import GraphExecutionService
from app.orchestration_runtime.worker import ModuleGraphWorker
from tests.postgresql_support import mvp_database
from tests.test_graph_model_adapter import install_transport
from tests.test_graph_postgresql import setup, cleanup, state


@asynccontextmanager
async def fault(db, rid, stage, boundary="write"):
    """Server-enforced failure restricted to this test's UUID run; always removed."""
    name = "receipt_fault_" + uuid.uuid4().hex
    conditions = {
        "reservation": "jsonb_array_length(NEW.input_json->'responses_retry'->'calls') > jsonb_array_length(OLD.input_json->'responses_retry'->'calls')",
        "receipt": "NEW.input_json->'responses_retry'->'calls'->-1->>'outcome' IS DISTINCT FROM OLD.input_json->'responses_retry'->'calls'->-1->>'outcome' AND OLD.input_json->'responses_retry'->'calls'->-1->>'outcome' = 'reserved'",
        "decision": "NEW.input_json->'responses_retry'->>'last_retry_decision' IS DISTINCT FROM OLD.input_json->'responses_retry'->>'last_retry_decision'",
        "failure": "NEW.status IN ('failed', 'queued') AND OLD.status = 'running'",
    }
    action = "PERFORM pg_terminate_backend(pg_backend_pid());" if boundary == "disconnect" else "RAISE EXCEPTION 'injected diagnostics persistence failure';"
    async with db() as session, session.begin():
        await session.execute(text(f"""CREATE FUNCTION {name}() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.run_id = '{rid}' AND ({conditions[stage]}) THEN
                    {action}
                END IF;
                RETURN NEW;
            END $$"""))
        trigger = (f"CREATE CONSTRAINT TRIGGER {name} AFTER UPDATE ON marketing_runs DEFERRABLE INITIALLY DEFERRED"
                   if boundary == "commit" else f"CREATE TRIGGER {name} BEFORE UPDATE ON marketing_runs")
        await session.execute(text(trigger + f" FOR EACH ROW EXECUTE FUNCTION {name}()"))
    try:
        yield
    finally:
        async with db() as session, session.begin():
            await session.execute(text(f"DROP TRIGGER {name} ON marketing_runs"))
            await session.execute(text(f"DROP FUNCTION {name}()"))


def provider(monkeypatch, mode):
    sends = []
    async def respond(request):
        sends.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("PRIVATE_PROVIDER_FAILURE", request=request)
        if mode == "cancel":
            raise asyncio.CancelledError()
        if mode == "rejected":
            return httpx.Response(200, json={"status": "incomplete", "incomplete_details": {"reason": "content_filter"}})
        return httpx.Response(mode if type(mode) is int else 200,
                              json={"status": "completed", "output_text": "{}"})
    install_transport(monkeypatch, respond)
    return sends


def restarted(db, service, clock):
    # New service and worker share only durable DB data, never live policy objects.
    return GraphExecutionService(db, executors=service.executors, clock=clock)


async def persisted(db, rid, jid):
    async with db() as session:
        run = await session.get(MarketingRun, rid)
        lease = await session.get(JobExecution, jid)
        markers = await session.scalar(select(func.count()).select_from(WorkerAttempt).where(WorkerAttempt.job_id == jid))
        return run, lease, markers


@pytest.mark.parametrize("boundary", ["write", "commit", "disconnect"])
@pytest.mark.parametrize("mode", [503, 408, "timeout", "rejected"])
def test_receipt_failure_keeps_provider_error_and_stops_without_resend(mvp_database, monkeypatch, caplog, boundary, mode):
    # Alembic roundtrip tests call fileConfig(disable_existing_loggers=True).
    # set_level alone cannot undo logger.disabled; isolate emission/redaction
    # assertions from that process-global state and restore it with monkeypatch.
    for name in ("app.orchestration_runtime.worker", "app.llm.openai_text"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", False)
        caplog.set_level(logging.INFO, logger=name)
    async def exercise():
        service, clock, rid, owner = await setup(mvp_database, production_model_call, responses_governance=True)
        jid = module_job_id(rid, 1, "competitor_analysis")
        sends = provider(monkeypatch, mode)
        try:
            async with fault(mvp_database, rid, "receipt", boundary):
                assert await ModuleGraphWorker(service).once(jid)
            run, lease, markers = await persisted(mvp_database, rid, jid)
            assert run.status == "failed" and lease.claim_token is lease.lease_until is None
            assert markers == 0 and lease.attempts == 1
            assert (await state(mvp_database, rid))[1][0].status is JobStatus.FAILED
            assert run.input_json["responses_retry"]["calls"][0]["outcome"] == "reserved"
            expected = "ReadTimeout" if mode == "timeout" else "ModelResponseError" if mode == "rejected" else "HTTPStatusError"
            assert "error_type=" + expected in caplog.text
            clock.tick()
            assert not await ModuleGraphWorker(restarted(mvp_database, service, clock)).once(jid)
            assert len(sends) == 1
            assert (await state(mvp_database, rid))[2] == []
            assert "PRIVATE_PROVIDER_FAILURE" not in caplog.text
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


@pytest.mark.parametrize("stage", ["receipt", "decision", "failure"])
@pytest.mark.parametrize("boundary", ["write", "commit", "disconnect"])
def test_outage_during_failure_handling_preserves_primary_and_recovers(mvp_database, monkeypatch, caplog, stage, boundary):
    """Receipt + decision both fail, or decision/failure alone; no early reclaim."""
    async def exercise():
        service, clock, rid, owner = await setup(mvp_database, production_model_call, responses_governance=True)
        jid = module_job_id(rid, 1, "competitor_analysis")
        sends = provider(monkeypatch, 408)
        try:
            async with fault(mvp_database, rid, stage, boundary):
                if stage == "receipt":
                    async with fault(mvp_database, rid, "decision", boundary):
                        with pytest.raises(httpx.HTTPStatusError) as caught:
                            await ModuleGraphWorker(service).once(jid)
                else:
                    with pytest.raises(httpx.HTTPStatusError) as caught:
                        await ModuleGraphWorker(service).once(jid)
            assert caught.value.response.status_code == 408
            assert any("persistence" in note for note in caught.value.__notes__)
            assert "injected diagnostics persistence failure" not in "".join(traceback.format_exception(caught.value))
            assert caught.value.__cause__ is None and caught.value.__suppress_context__
            run, lease, markers = await persisted(mvp_database, rid, jid)
            assert run.status == "running" and lease.claim_token and lease.lease_until
            assert markers == 0 and lease.attempts == 1
            job = (await state(mvp_database, rid))[1][0]
            assert job.status is JobStatus.RUNNING and job.version == 1
            calls = run.input_json["responses_retry"]["calls"]
            assert len(calls) == 1 and calls[0]["outcome"] == ("reserved" if stage == "receipt" else "unknown")
            if stage == "decision":
                assert "last_retry_decision" not in run.input_json["responses_retry"]
            if stage == "failure":
                assert calls[0]["retry_decision"].startswith("stop_")
            replacement = restarted(mvp_database, service, clock)
            assert await replacement.claim(jid) is None
            clock.tick()
            # Competing replacement workers must admit only one new owner.
            results = await asyncio.gather(ModuleGraphWorker(replacement).once(jid),
                ModuleGraphWorker(restarted(mvp_database, service, clock)).once(jid))
            assert sorted(results) == [False, True]
            run, lease, markers = await persisted(mvp_database, rid, jid)
            assert run.status == "failed" and lease.attempts == 2
            assert lease.claim_token is lease.lease_until is None and markers == 0
            job = (await state(mvp_database, rid))[1][0]
            assert job.status is JobStatus.FAILED and job.version == 2
            assert len(sends) == 1 and (await state(mvp_database, rid))[2] == []
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


@pytest.mark.parametrize("mode", ["success", "cancel"])
@pytest.mark.parametrize("boundary", ["write", "commit", "disconnect"])
def test_success_or_cancellation_receipt_failure_retains_lease_then_fences_old_owner(mvp_database, monkeypatch, mode, boundary):
    async def exercise():
        service, clock, rid, owner = await setup(mvp_database, production_model_call, responses_governance=True)
        jid = module_job_id(rid, 1, "competitor_analysis")
        sends = provider(monkeypatch, mode)
        try:
            async with fault(mvp_database, rid, "receipt", boundary):
                with pytest.raises(SQLAlchemyError if mode == "success" else asyncio.CancelledError):
                    await ModuleGraphWorker(service).once(jid)
            run, lease, markers = await persisted(mvp_database, rid, jid)
            assert run.status == "running" and lease.claim_token and markers == 0
            old = GraphWorkItem(jid, rid, 1, "competitor_analysis", lease.claim_token, lease.attempts)
            assert run.input_json["responses_retry"]["calls"][0]["outcome"] == "reserved"
            replacement = restarted(mvp_database, service, clock)
            assert await replacement.claim(jid) is None
            clock.tick()
            new = await replacement.claim(jid)
            assert new.claim_token != old.claim_token and new.attempt == 2
            # Old owner cannot change even diagnostic state or the new owner's lease.
            assert not await service.fail(old, code="execution_invalid")
            assert not await service.finish(old, None, None)
            with pytest.raises(RetryGovernanceError, match="inactive"):
                await service._provider_receipt(old, {}, finished=True)
            assert (await persisted(mvp_database, rid, jid))[1].claim_token == new.claim_token
            binding, request = await replacement.load_work(new)
            with graph_call_context(new, request, None, await replacement.provider_hooks(new)):
                with pytest.raises(RetryGovernanceError, match="requires_owner_decision"):
                    await ModuleExecutorDispatcher(replacement.executors).dispatch(binding, request)
            await replacement.fail(new, code="execution_invalid")
            run, lease, markers = await persisted(mvp_database, rid, jid)
            assert run.status == "failed" and lease.claim_token is lease.lease_until is None and markers == 0
            assert len(sends) == 1
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


@pytest.mark.parametrize("stage", ["decision", "failure"])
def test_explicit_503_retry_after_rollback_is_bounded_and_releases_lease(mvp_database, monkeypatch, stage):
    async def exercise():
        service, clock, rid, owner = await setup(mvp_database, production_model_call, responses_governance=True)
        jid = module_job_id(rid, 1, "competitor_analysis")
        sends = provider(monkeypatch, 503)
        try:
            async with fault(mvp_database, rid, stage, "commit"):
                with pytest.raises(httpx.HTTPStatusError) as caught:
                    await ModuleGraphWorker(service).once(jid)
            assert caught.value.response.status_code == 503
            assert (await persisted(mvp_database, rid, jid))[0].status == "running"
            replacement = restarted(mvp_database, service, clock)
            assert await replacement.claim(jid) is None
            clock.tick()
            assert await ModuleGraphWorker(replacement).once(jid)
            run, lease, markers = await persisted(mvp_database, rid, jid)
            assert run.status == "queued" and lease.claim_token is lease.lease_until is None and markers == 0
            assert not await ModuleGraphWorker(replacement).once(jid)
            clock.tick(11)
            assert await ModuleGraphWorker(replacement).once(jid)
            run, lease, markers = await persisted(mvp_database, rid, jid)
            assert run.status == "failed" and lease.attempts == 3 and markers == 0
            assert lease.claim_token is lease.lease_until is None and len(sends) == 3
            assert len(run.input_json["responses_retry"]["calls"]) == 3
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())


def test_reservation_commit_failure_sends_nothing_and_can_recover(mvp_database, monkeypatch):
    async def exercise():
        service, clock, rid, owner = await setup(mvp_database, production_model_call, responses_governance=True)
        jid = module_job_id(rid, 1, "competitor_analysis")
        sends = provider(monkeypatch, 408)
        try:
            async with fault(mvp_database, rid, "reservation", "commit"):
                with pytest.raises(SQLAlchemyError):
                    await ModuleGraphWorker(service).once(jid)
            run, lease, markers = await persisted(mvp_database, rid, jid)
            assert run.input_json["responses_retry"]["calls"] == [] and len(sends) == 0
            assert run.status == "running" and lease.claim_token and markers == 0
            clock.tick()
            assert await ModuleGraphWorker(restarted(mvp_database, service, clock)).once(jid)
            assert len(sends) == 1 and (await persisted(mvp_database, rid, jid))[0].status == "failed"
        finally:
            await cleanup(mvp_database, rid, owner)
    asyncio.run(exercise())
