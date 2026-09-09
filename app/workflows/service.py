from __future__ import annotations

import copy
import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from app.config import settings
from app.db import AsyncSessionLocal
from app.models import BrandProfile, Job, JobExecution, JobStatus, MarketingArtifact, MarketingRun, User, WorkflowDelivery
from app.services.brand_profile_service import BrandProfileService
from app.services.job_persistence_service import JobPersistenceService
from app.workflows.schemas import BusinessInput, StartRequest


def utcnow():
    return datetime.now(timezone.utc)


def stable_id(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]


class WorkflowError(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class WorkItem:
    job_id: str
    run_id: str
    step: str
    token: str
    snapshot: dict
    artifacts: dict


class MarketingWorkflowService:
    def __init__(self, sessions=AsyncSessionLocal, *, queue=None, clock=utcnow):
        self.sessions, self.queue, self.clock = sessions, queue, clock
        self.jobs = JobPersistenceService(clock)

    async def _user(self, session, actor):
        await session.execute(insert(User).values(telegram_id=actor).on_conflict_do_nothing(index_elements=[User.telegram_id]))
        return await session.scalar(select(User).where(User.telegram_id == actor).with_for_update())

    async def _owned(self, session, actor, run_id, *, lock=False):
        query = select(MarketingRun).join(User).where(
            MarketingRun.run_id == run_id, User.telegram_id == actor,
            MarketingRun.workflow_type == "marketing_mvp.v1",
        )
        if lock:
            query = query.with_for_update(of=MarketingRun)
        run = await session.scalar(query.execution_options(populate_existing=True))
        if run is None:
            raise WorkflowError("Проект не найден.", 404)
        return run

    async def _enqueue(self, session, run, step):
        job_id = stable_id(f"{run.run_id}:{step}")
        existing = await session.get(Job, job_id)
        if existing is not None:
            return job_id
        await self.jobs.create_job(session, kind="marketing.step", marketing_run_id=run.run_id,
                                   workflow_step=step, job_id=job_id,
                                   payload_json={"schema_version": "workflow_job.v1", "step": step, "run_id": run.run_id})
        session.add(JobExecution(job_id=job_id, available_at=self.clock()))
        run.status, run.current_step, run.error = "queued", step, None
        run.updated_at = self.clock().replace(tzinfo=None)
        return job_id

    @staticmethod
    def missing(snapshot):
        return [field for field in ("product", "audience", "goal") if not snapshot.get(field)]

    async def _wake(self, job_id):
        if self.queue and job_id:
            await self.queue.wake(job_id)  # best effort; DB scan is authoritative

    async def start(self, actor: int, request: StartRequest):
        job_id = None
        async with self.sessions() as session, session.begin():
            user = await self._user(session, actor)
            run_id = stable_id(f"marketing_mvp:{user.id}:{request.request_key}")
            run = await session.get(MarketingRun, run_id)
            raw = request.model_dump(mode="json")
            if run:
                if run.state_json.get("request") != raw:
                    raise WorkflowError("Ключ запроса уже использован с другими данными.")
            else:
                profile = await BrandProfileService.get_by_user_id(session, user.id)
                brand = BrandProfileService.to_context(profile)
                snapshot = {
                    "schema_version": "business_snapshot.v1", "telegram_id": actor,
                    "competitor_url": request.competitor_url,
                    "product": request.product or brand.get("product_description", ""),
                    "audience": request.audience or brand.get("audience", ""),
                    "goal": request.goal or "; ".join(brand.get("goals", []) or []),
                    "brand": brand, "captured_at": self.clock().isoformat(),
                }
                run = MarketingRun(run_id=run_id, user_id=user.id, workflow_type="marketing_mvp.v1",
                                   status="needs_input", current_step="analysis", input_json=snapshot,
                                   state_json={"request": raw})
                session.add(run)
                await session.flush()
                if not self.missing(snapshot):
                    job_id = await self._enqueue(session, run, "analysis")
        await self._wake(job_id)
        return await self.status(actor, run_id)

    async def context(self, actor, run_id, values: BusinessInput):
        job_id = None
        async with self.sessions() as session, session.begin():
            run = await self._owned(session, actor, run_id, lock=True)
            if run.status != "needs_input":
                # A repeated submitted context cannot mutate an executing run.
                if any(v and run.input_json.get(k) != v for k, v in values.model_dump().items()):
                    raise WorkflowError("Контекст выполняемого проекта уже зафиксирован.")
            else:
                run.input_json = {**run.input_json, **{k: v for k, v in values.model_dump().items() if v}}
                if not self.missing(run.input_json):
                    job_id = await self._enqueue(session, run, "analysis")
        await self._wake(job_id)
        return await self.status(actor, run_id)

    async def set_profile(self, actor, values):
        async with self.sessions() as session:
            user = await self._user(session, actor)
            # BrandProfileService explicitly owns this isolated transaction.
            profile = await BrandProfileService.upsert_for_user(session, user.id, values)
            return BrandProfileService.to_context(profile)

    async def continue_run(self, actor, run_id, action):
        if action not in {"creative", "mentor"}:
            raise WorkflowError("Неизвестный шаг.", 422)
        async with self.sessions() as session, session.begin():
            run = await self._owned(session, actor, run_id, lock=True)
            predecessor = "analysis" if action == "creative" else "creative"
            exists = await session.scalar(select(MarketingArtifact.id).where(
                MarketingArtifact.run_id == run_id, MarketingArtifact.artifact_key == predecessor,
            ))
            if exists is None:
                raise WorkflowError("Сначала завершите предыдущий шаг.")
            job_id = await self._enqueue(session, run, action)
        await self._wake(job_id)
        return await self.status(actor, run_id)

    async def status(self, actor, run_id):
        async with self.sessions() as session:
            run = await self._owned(session, actor, run_id)
            artifacts = (await session.scalars(select(MarketingArtifact).where(MarketingArtifact.run_id == run_id))).all()
            jobs = (await session.scalars(select(Job).where(Job.marketing_run_id == run_id).order_by(Job.created_at))).all()
            delivery = (await session.scalars(select(WorkflowDelivery).join(Job).where(Job.marketing_run_id == run_id))).all()
            return {
                "run_id": run_id, "status": run.status, "current_step": run.current_step, "error": run.error,
                "missing_fields": self.missing(run.input_json) if run.status == "needs_input" else [],
                "artifacts": {a.artifact_key: a.payload_json for a in artifacts},
                "jobs": [{"job_id": j.job_id, "step": j.workflow_step, "status": j.status.value, "error": j.error} for j in jobs],
                "delivery": [{"id": d.delivery_id, "status": d.status, "part": d.part} for d in delivery],
            }

    async def recent(self, actor):
        async with self.sessions() as session:
            runs = (await session.scalars(select(MarketingRun).join(User).where(
                User.telegram_id == actor, MarketingRun.workflow_type == "marketing_mvp.v1",
            ).order_by(MarketingRun.created_at.desc()).limit(10))).all()
            return [{"run_id": r.run_id, "status": r.status, "step": r.current_step} for r in runs]

    async def retry_delivery(self, actor, run_id):
        async with self.sessions() as session, session.begin():
            await self._owned(session, actor, run_id, lock=True)
            rows = (await session.scalars(select(WorkflowDelivery).join(Job).where(
                Job.marketing_run_id == run_id, WorkflowDelivery.status == "failed",
            ).with_for_update(of=WorkflowDelivery))).all()
            for row in rows:
                row.status, row.attempts, row.error = "pending", 0, None
                row.available_at = self.clock()
        return await self.status(actor, run_id)

    async def claim(self, job_id=None):
        now = self.clock()
        async with self.sessions() as session, session.begin():
            query = select(JobExecution).join(Job).where(
                Job.kind == "marketing.step", Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
                JobExecution.available_at <= now,
                or_(JobExecution.lease_until.is_(None), JobExecution.lease_until <= now),
            )
            if job_id:
                query = query.where(Job.job_id == job_id)
            lease = await session.scalar(query.order_by(JobExecution.available_at, JobExecution.job_id)
                                         .with_for_update(of=JobExecution, skip_locked=True).limit(1))
            if lease is None:
                return None
            job = await session.get(Job, lease.job_id)
            if job.status is JobStatus.PENDING:
                job = await self.jobs.transition_job(session, job.job_id, job.version, JobStatus.RUNNING)
            run = await session.get(MarketingRun, job.marketing_run_id)
            if lease.attempts >= 3:
                await self._fail_locked(session, lease, job, run, "Лимит попыток исчерпан после остановки worker. Создайте новый запрос.")
                return None
            lease.attempts += 1
            lease.claim_token = uuid.uuid4().hex
            lease.lease_until = now + timedelta(seconds=settings.WORKFLOW_TIMEOUT_SECONDS + 30)
            run.status, run.current_step = "running", job.workflow_step
            artifacts = (await session.scalars(select(MarketingArtifact).where(MarketingArtifact.run_id == run.run_id))).all()
            return WorkItem(job.job_id, run.run_id, job.workflow_step, lease.claim_token,
                            copy.deepcopy(run.input_json), {a.artifact_key: copy.deepcopy(a.payload_json) for a in artifacts})

    async def _active(self, session, item):
        lease = await session.scalar(select(JobExecution).where(JobExecution.job_id == item.job_id).with_for_update())
        if lease is None or lease.claim_token != item.token or lease.lease_until <= self.clock():
            return None
        job = await session.get(Job, item.job_id)
        if job.status is not JobStatus.RUNNING:
            return None
        return lease, job, await session.get(MarketingRun, item.run_id)

    def _deliveries(self, session, job_id, parts):
        for part, payload in enumerate(parts):
            session.add(WorkflowDelivery(job_id=job_id, part=part, payload_json=payload, available_at=self.clock()))

    async def finish(self, item, artifact, parts):
        async with self.sessions() as session, session.begin():
            active = await self._active(session, item)
            if active is None:
                return False
            lease, job, run = active
            session.add(MarketingArtifact(run_id=item.run_id, artifact_key=item.step,
                                           artifact_type=artifact["schema_version"], step=item.step, payload_json=artifact))
            await self.jobs.transition_job(session, job.job_id, job.version, JobStatus.SUCCEEDED,
                                           result_json={"artifact_key": item.step, "schema_version": artifact["schema_version"]})
            run.status = {"analysis": "awaiting_creative", "creative": "awaiting_mentor", "mentor": "completed"}[item.step]
            run.error, run.updated_at = None, self.clock().replace(tzinfo=None)
            lease.claim_token = lease.lease_until = None
            self._deliveries(session, job.job_id, parts)
        return True

    async def _fail_locked(self, session, lease, job, run, message):
        await self.jobs.transition_job(session, job.job_id, job.version, JobStatus.FAILED, error=message)
        run.status, run.error = "failed", message
        run.updated_at = self.clock().replace(tzinfo=None)
        lease.claim_token = lease.lease_until = None
        self._deliveries(session, job.job_id, [{"kind": "text", "text": f"Проект {run.run_id}: {message}"}])

    async def fail(self, item, *, retryable: bool, message: str):
        async with self.sessions() as session, session.begin():
            active = await self._active(session, item)
            if active is None:
                return False
            lease, job, run = active
            if retryable and lease.attempts < 3:
                lease.claim_token = lease.lease_until = None
                lease.available_at = self.clock() + timedelta(seconds=5 * 2 ** (lease.attempts - 1))
                run.status = "queued"
            else:
                await self._fail_locked(session, lease, job, run, message)
        return True
