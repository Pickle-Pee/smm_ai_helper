"""Operator fencing, migration lifecycle and SIGTERM after a real PostgreSQL drain."""
import asyncio
import os
import signal
import uuid
from unittest.mock import AsyncMock

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import ProgrammingError

from app.config import settings
from app.models import Job, WorkerAdmission
from app.services.worker_drain_service import ControlError, WorkerDrainControl
from app.worker import main
from tests.postgresql_support import mvp_database
from tests.test_worker_drain_postgresql import finish, lane_run


def test_control_epoch_fences_stale_evidence_and_idempotent_commands(mvp_database):
    async def exercise():
        control = WorkerDrainControl(mvp_database)
        await control.resume()
        paused = await control.pause()
        assert (await control.pause(expected_epoch=paused["epoch"]))["epoch"] == paused["epoch"]
        results = await asyncio.gather(control.resume(expected_epoch=paused["epoch"]),
                                       control.resume(expected_epoch=paused["epoch"]), return_exceptions=True)
        assert sum(isinstance(r, ControlError) for r in results) == 1
        with pytest.raises(ControlError):
            await control.status(expected_epoch=paused["epoch"], require_drained=True)
        reopened = await control.status()
        assert reopened["epoch"] == paused["epoch"] + 1 and reopened["admission"] == "open"
        paused_again = await control.pause()
        assert paused_again["epoch"] == paused["epoch"] + 2
        try:
            with pytest.raises(ControlError):
                await control.status(expected_epoch=paused["epoch"], require_drained=True)
        finally:
            await control.resume()
    asyncio.run(exercise())


def test_missing_control_row_never_admits_and_is_not_recreated(mvp_database):
    async def exercise():
        async with lane_run(mvp_database, "fixed") as fixed, lane_run(mvp_database, "graph") as graph:
            # This module runs sequentially on an explicitly disposable database.
            async with mvp_database() as session, session.begin():
                row = await session.get(WorkerAdmission, "workers")
                saved = dict(id=row.id, paused=row.paused, epoch=row.epoch)
                await session.execute(text("DELETE FROM worker_admission"))
            try:
                for service in (fixed.service, graph.service):
                    with pytest.raises(ControlError):
                        await service.claim()
                with pytest.raises(ControlError):
                    await fixed.control.status(require_drained=True)
                async with mvp_database() as session:
                    assert await session.scalar(select(WorkerAdmission)) is None
            finally:
                async with mvp_database() as session, session.begin():
                    session.add(WorkerAdmission(**saved))
    asyncio.run(exercise())


def test_worker_role_can_lock_but_cannot_open_admission(mvp_database):
    async def exercise():
        from app.services.worker_drain_service import claim_admitted, record_attempt, end_attempt
        worker_role = "drain_worker_" + uuid.uuid4().hex
        operator_role = "drain_operator_" + uuid.uuid4().hex
        async with mvp_database() as session, session.begin():
            job_id, token = uuid.uuid4().hex, uuid.uuid4().hex
            session.add(Job(job_id=job_id, kind="marketing.step", status="pending", payload_json={}))
            await session.flush()
            # Roles/grants and mutations all roll back; production is never touched.
            for role in (worker_role, operator_role):
                await session.execute(text(f'CREATE ROLE "{role}"'))
                await session.execute(text(f'GRANT SELECT ON worker_admission TO "{role}"'))
            await session.execute(text(f'GRANT UPDATE(id) ON worker_admission TO "{worker_role}"'))
            await session.execute(text(f'GRANT SELECT(job_id, claim_token), INSERT, DELETE ON worker_attempts TO "{worker_role}"'))
            await session.execute(text(f'GRANT UPDATE(paused, epoch) ON worker_admission TO "{operator_role}"'))
            await session.execute(text(f'GRANT SELECT(job_id, kind, status) ON jobs TO "{operator_role}"'))
            await session.execute(text(f'GRANT SELECT(job_id, claim_token, lease_until, available_at) ON job_executions TO "{operator_role}"'))
            await session.execute(text(f'GRANT SELECT(job_id, claim_token) ON worker_attempts TO "{operator_role}"'))
            await session.execute(text(f'SET LOCAL ROLE "{worker_role}"'))
            assert isinstance(await claim_admitted(session), bool)
            record_attempt(session, job_id, token)
            await session.flush()
            await end_attempt(session, job_id, token)
            with pytest.raises(ProgrammingError):
                async with session.begin_nested():
                    await session.execute(text("UPDATE worker_admission SET paused = false"))
            await session.execute(text("RESET ROLE"))
            await session.execute(text(f'SET LOCAL ROLE "{operator_role}"'))
            await session.execute(text("UPDATE worker_admission SET paused = true, epoch = epoch + 1"))
            row = await session.scalar(select(WorkerAdmission).with_for_update(read=True)
                                       .execution_options(populate_existing=True))
            assert (await WorkerDrainControl._snapshot(session, row))["admission"] == "paused"
            await session.execute(text("RESET ROLE"))
            await session.rollback()
    asyncio.run(exercise())


def test_sigterm_callback_after_drain_preserves_pending_jobs_and_restart_pause(mvp_database, monkeypatch):
    async def exercise():
        async with lane_run(mvp_database, "fixed") as fixed, lane_run(mvp_database, "graph") as graph:
            a, b = await asyncio.gather(fixed.service.claim(fixed.job_id), graph.service.claim(graph.job_id))
            paused = await fixed.control.pause()
            assert await finish(fixed, a) and await finish(graph, b)
            status = await fixed.control.status(expected_epoch=paused["epoch"], require_drained=True)
            assert status["drained"] and status["lanes"]["graph"]["pending_jobs"] > 0
            loop = asyncio.get_running_loop()
            signals, queues = {}, []
            monkeypatch.setattr(loop, "add_signal_handler", lambda sig, callback: signals.update({sig: callback}))
            monkeypatch.setattr(loop, "remove_signal_handler", lambda sig: True)
            monkeypatch.setattr(settings, "WORKER_CONCURRENCY", 1)
            monkeypatch.setattr(settings, "GRAPH_WORKER_CONCURRENCY", 1)
            from types import SimpleNamespace
            for _ in range(2):
                ready = asyncio.Event()
                waited = set()
                def queue_factory(*, key):
                    async def wait():
                        waited.add(key)
                        if len(waited) == 2:
                            ready.set()
                        await asyncio.Event().wait()
                    queue = SimpleNamespace(key=key, wait=wait, close=AsyncMock())
                    queues.append(queue)
                    return queue
                worker = asyncio.create_task(main(sessions=mvp_database, queue_factory=queue_factory))
                try:
                    await asyncio.wait_for(ready.wait(), 10)
                    # This is the same callback installed for OS SIGTERM on POSIX.
                    # scripts/check_worker_lanes.py verifies actual container signal in CI.
                    signals[signal.SIGTERM]()
                    with pytest.raises(asyncio.CancelledError):
                        await worker
                finally:
                    if not worker.done():
                        worker.cancel()
                    await asyncio.gather(worker, return_exceptions=True)
                after = await graph.control.status(expected_epoch=paused["epoch"], require_drained=True)
                assert after["lanes"] == status["lanes"] and after["drained"]
            assert all(q.close.await_count == 1 for q in queues)
    asyncio.run(exercise())


def test_admission_migration_roundtrip_and_metadata_match(mvp_database, monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", os.environ["MVP_TEST_DATABASE_URL"])
    # Alembic's fileConfig must not disable loggers owned by later tests.
    monkeypatch.setattr("logging.config.fileConfig", lambda *args, **kwargs: None)
    config = Config("alembic.ini")
    engine = create_engine(settings.DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    try:
        command.downgrade(config, "20261006_0011")
        with engine.connect() as connection:
            assert not inspect(connection).has_table("worker_admission")
        command.upgrade(config, "head")
        command.check(config)
        with engine.connect() as connection:
            row = connection.execute(text("SELECT id, paused, epoch FROM worker_admission")).one()
            assert tuple(row) == ("workers", False, 0)
    finally:
        command.upgrade(config, "head")
        engine.dispose()
