"""PostgreSQL claim barrier. No control lock survives a claim transaction.

Claims take SHARE before any run/lease lock; control takes UPDATE. Pause commit
therefore waits for all preceding claim commits and blocks later claims. Completion
never takes this lock, so admitted work keeps its original fencing/retry policy.
"""
from sqlalchemy import delete, func, select, union

from app.models import Job, JobExecution, JobStatus, WorkerAdmission, WorkerAttempt


class ControlError(RuntimeError):
    """Content-free operator failure."""


async def _locked(session, *, shared=False):
    row = await session.scalar(select(WorkerAdmission).where(
        WorkerAdmission.id == "workers").with_for_update(read=shared))
    if row is None:
        raise ControlError("admission control missing; migrate before running workers")
    return row


async def claim_admitted(session):
    """Must run FIRST inside the transaction that commits a new claim."""
    return not (await _locked(session, shared=True)).paused


def record_attempt(session, job_id, claim_token):
    session.add(WorkerAttempt(job_id=job_id, claim_token=claim_token))


async def end_attempt(session, job_id, claim_token):
    """Clear only this attempt, never a replacement's marker or Job lease."""
    await session.execute(delete(WorkerAttempt).where(
        WorkerAttempt.job_id == job_id, WorkerAttempt.claim_token == claim_token))


async def release_attempt(sessions, job_id, claim_token):
    async with sessions() as session, session.begin():
        await end_attempt(session, job_id, claim_token)


class WorkerDrainControl:
    def __init__(self, sessions):
        self.sessions = sessions

    @staticmethod
    def _epoch(row, expected_epoch):
        if expected_epoch is not None and row.epoch != expected_epoch:
            raise ControlError("admission epoch changed")

    async def pause(self, *, expected_epoch=None):
        return await self._change(True, expected_epoch)

    async def resume(self, *, expected_epoch=None):
        return await self._change(False, expected_epoch)

    async def _change(self, paused, expected_epoch):
        async with self.sessions() as session, session.begin():
            row = await _locked(session)
            self._epoch(row, expected_epoch)
            if row.paused != paused:
                row.paused = paused
                row.epoch += 1
                await session.flush()
            result = await self._snapshot(session, row)
        # Returning only after commit is essential for acknowledged pause.
        return result

    async def status(self, *, expected_epoch=None, require_drained=False):
        async with self.sessions() as session, session.begin():
            row = await _locked(session, shared=True)
            self._epoch(row, expected_epoch)
            result = await self._snapshot(session, row)
            if require_drained and not result["drained"]:
                raise ControlError("workers are not drained")
        return result

    @staticmethod
    async def _snapshot(session, row):
        # Keep each attempt's identity after lease replacement. UNION also includes
        # pre-control current tokens conservatively, without counting a current
        # marker twice. One statement/snapshot covers both lanes and populations.
        now = func.statement_timestamp()
        attempts = union(
            select(WorkerAttempt.job_id, WorkerAttempt.claim_token),
            select(JobExecution.job_id, JobExecution.claim_token).where(JobExecution.claim_token.is_not(None)),
        ).subquery()
        outstanding = select(attempts.c.job_id, func.count().label("count")).group_by(
            attempts.c.job_id).subquery()
        counts = (await session.execute(select(
            Job.kind,
            func.sum(func.coalesce(outstanding.c.count, 0)),
            func.count().filter(JobExecution.lease_until > now),
            func.count().filter(JobExecution.claim_token.is_(None),
                                Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING])),
            func.count().filter(JobExecution.claim_token.is_(None),
                                Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
                                JobExecution.available_at > now),
        ).outerjoin(JobExecution).outerjoin(outstanding, outstanding.c.job_id == Job.job_id)
            .where(Job.kind.in_(["marketing.step", "orchestration.module"]))
            .group_by(Job.kind))).all()
        lanes = {name: dict(outstanding_attempts=0, active_leases=0, pending_jobs=0, deferred_jobs=0)
                 for name in ("fixed", "graph")}
        for kind, outstanding, active, pending, deferred in counts:
            name = "fixed" if kind == "marketing.step" else "graph"
            lanes[name] = dict(outstanding_attempts=int(outstanding), active_leases=active,
                               pending_jobs=pending, deferred_jobs=deferred)
        observed = await session.scalar(select(func.statement_timestamp()))
        return {"schema_version": "worker_drain.v1", "epoch": row.epoch,
                "admission": "paused" if row.paused else "open",
                "observed_at": observed.isoformat(), "lanes": lanes,
                "drained": row.paused and all(lane["outstanding_attempts"] == 0
                                               for lane in lanes.values())}
