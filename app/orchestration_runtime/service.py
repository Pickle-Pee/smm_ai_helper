"""PostgreSQL owns graph state. Every mutation locks run -> lease -> Job.

No method holds a transaction across executor/provider calls. Completion and
advance share a transaction so a crash cannot strand a dependency-ready node.
"""
from dataclasses import replace
import json

from datetime import datetime, timedelta, timezone
import logging
import uuid

from sqlalchemy import exists, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.db import AsyncSessionLocal
from app.models import Job, JobExecution, JobStatus, MarketingArtifact, MarketingRun, OrchestrationPlanRecord, User
from app.services.job_persistence_service import JobPersistenceService
from app.module_execution import ModuleExecutionRequest, UpstreamExecutionResult
from app.module_execution.acceptance import fully_accepted
from app.marketing_orchestrator.quality_gates import QualityGateEvaluator
from app.marketing_orchestrator.quality_gates.contracts import EvaluationBatch
from app.module_registry import ModuleResultStatus
from .compiler import validate_compiled_plan
from .contracts import ARTIFACT_SCHEMA, JOB_KIND, WORKFLOW_TYPE, GraphWorkItem, artifact_key, module_job_id, validate_identity, optional, hard_predecessors, CompiledExecutionPlanV2
from .errors import RuntimeContractError, StartIdentityConflict
from .serialization import bounded, fingerprint, plan_from_json, plan_to_json, result_from_json, result_to_json

log = logging.getLogger(__name__)
TERMINAL = {"completed", "completed_with_limitations", "blocked", "failed"}


def utcnow():
    return datetime.now(timezone.utc)


def routing(run_id, revision, plan, node):
    return {"schema_version": "module_job.v1", "run_id": run_id, "plan_revision": revision,
            "plan_fingerprint": plan.execution_fingerprint, "node_id": node.node_id,
            "module_id": node.module_id.value, "executor_key": node.binding.executor_key,
            "registry_version": plan.registry_version}


def evaluate_result(job_id, result, upstream):
    batch = EvaluationBatch(batch_id="bat_" + job_id,
                            results=tuple(u.result.normalized_result for u in upstream) + (result.normalized_result,))
    evaluation = QualityGateEvaluator().evaluate(batch)
    manifest = evaluation.synthesis_manifest
    return {"schema_version": "module_quality.v1", "batch_id": batch.batch_id,
            "batch_fingerprint": batch.batch_fingerprint,
            "accepted_result_ids": list(manifest.accepted_result_ids),
            "accepted_claim_ids": list(manifest.accepted_claim_ids)}


class GraphExecutionService:
    def __init__(self, sessions=AsyncSessionLocal, *, executors, queue=None, clock=utcnow,
                 lease_seconds=330, max_attempts=3):
        if lease_seconds <= 0 or not 1 <= max_attempts <= 10:
            raise ValueError("invalid execution policy")
        self.sessions, self.executors, self.queue, self.clock = sessions, executors, queue, clock
        self.lease_seconds, self.max_attempts = lease_seconds, max_attempts
        self.jobs = JobPersistenceService(clock)

    async def _wake(self, jobs):
        if self.queue is not None:
            for job_id in jobs:
                try:
                    await self.queue.wake(job_id)
                except Exception as exc:
                    log.warning("Graph wakeup unavailable job_id=%s error_type=%s", job_id, type(exc).__name__)

    async def _run(self, session, run_id):
        run = await session.scalar(select(MarketingRun).where(
            MarketingRun.run_id == run_id, MarketingRun.workflow_type == WORKFLOW_TYPE,
        ).with_for_update())
        if run is None:
            raise RuntimeContractError("graph run not found")
        return run

    async def _plan(self, session, run_id):
        row = await session.scalar(select(OrchestrationPlanRecord).where(
            OrchestrationPlanRecord.run_id == run_id, OrchestrationPlanRecord.status == "active"))
        if row is None or row.revision != 1:
            raise RuntimeContractError("missing or unsupported active revision")
        plan = plan_from_json(row.compiled_plan_json)
        if (row.source_plan_id != plan.source_plan_id or row.registry_version != plan.registry_version
                or row.compiled_plan_fingerprint != plan.execution_fingerprint):
            raise RuntimeContractError("persisted plan identity mismatch")
        validate_compiled_plan(plan, self.executors)
        return row.revision, plan

    async def start_compiled_run(self, *, owner_id: int, run_id: str, plan):
        # Caller owns authorization. Revalidate before opening any DB session.
        validate_identity(run_id, 1, "start")
        if type(owner_id) is not int or owner_id <= 0:
            raise RuntimeContractError("authorized owner required")
        raw = plan_to_json(plan)
        plan = plan_from_json(raw)
        validate_compiled_plan(plan, self.executors)
        async with self.sessions() as session, session.begin():
            if await session.get(User, owner_id) is None:
                raise RuntimeContractError("owner not found")
            # ON CONFLICT waits for concurrent start, then exact identity is checked.
            created = await session.scalar(insert(MarketingRun).values(
                run_id=run_id, user_id=owner_id, workflow_type=WORKFLOW_TYPE, status="queued",
                input_json={}, state_json={},
            ).on_conflict_do_nothing(index_elements=[MarketingRun.run_id]).returning(MarketingRun.run_id))
            run = await session.scalar(select(MarketingRun).where(MarketingRun.run_id == run_id).with_for_update())
            if run.user_id != owner_id or run.workflow_type != WORKFLOW_TYPE:
                raise StartIdentityConflict("run identity already owned")
            if created:
                session.add(OrchestrationPlanRecord(
                    run_id=run_id, revision=1, source_plan_id=plan.source_plan_id,
                    compiled_plan_fingerprint=plan.execution_fingerprint, registry_version=plan.registry_version,
                    compiled_plan_json=raw, status="active",
                ))
                await session.flush()
            else:
                _, existing = await self._plan(session, run_id)
                if plan != existing:
                    raise StartIdentityConflict("run identity has a different plan")
            wake = await self._advance_locked(session, run)
        await self._wake(wake)
        return run_id

    async def _graph_state(self, session, run_id, revision, plan):
        nodes = {n.node_id: n for n in plan.nodes}
        jobs = {}
        for job in (await session.scalars(select(Job).where(Job.marketing_run_id == run_id))).all():
            node = nodes.get(job.workflow_step)
            if node is None or job.kind != JOB_KIND or job.job_id != module_job_id(run_id, revision, node.node_id) or job.payload_json != routing(run_id, revision, plan, node):
                raise RuntimeContractError("job routing mismatch")
            if node.node_id in jobs:
                raise RuntimeContractError("duplicate node Job")
            jobs[node.node_id] = job
        accepted = {}
        rows = (await session.scalars(select(MarketingArtifact).where(MarketingArtifact.run_id == run_id))).all()
        by_key = {a.artifact_key: a for a in rows}
        for node in plan.nodes:
            row = by_key.pop(artifact_key(run_id, revision, node.node_id), None)
            job = jobs.get(node.node_id)
            if row is None:
                if job and job.status is JobStatus.SUCCEEDED:
                    raise RuntimeContractError("successful Job missing artifact")
                continue
            raw = bounded(row.payload_json)
            if (set(raw) != {"schema_version", "run_id", "plan_revision", "node_id", "module_id", "execution_result", "quality"}
                    or raw["schema_version"] != ARTIFACT_SCHEMA or raw["run_id"] != run_id
                    or type(raw["plan_revision"]) is not int or raw["plan_revision"] != revision
                    or raw["node_id"] != node.node_id or raw["module_id"] != node.module_id.value
                    or row.artifact_type != ARTIFACT_SCHEMA or row.step != node.node_id):
                raise RuntimeContractError("artifact envelope mismatch")
            if job is None or job.status is not JobStatus.SUCCEEDED or job.result_json != {
                "artifact_key": row.artifact_key, "artifact_fingerprint": fingerprint(raw), "schema_version": ARTIFACT_SCHEMA,
            }:
                raise RuntimeContractError("artifact has no matching successful Job")
            result = result_from_json(raw["execution_result"])
            if result.module_id is not node.module_id or not self._ready(plan, node, jobs, accepted):
                raise RuntimeContractError("artifact module or dependencies mismatch")
            upstream = self._upstream(plan, node, accepted)
            quality = evaluate_result(job.job_id, result, upstream)
            if raw["quality"] != quality or not fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"]):
                raise RuntimeContractError("artifact quality acceptance mismatch")
            accepted[node.node_id] = result
        if by_key:
            raise RuntimeContractError("unknown artifact identity")
        return jobs, accepted

    @staticmethod
    def _upstream(plan, node, accepted):
        # Full ancestor closure is required to restore transitive claim lineage.
        wanted = set(node.dependency_node_ids)
        for candidate in reversed(plan.nodes):
            if candidate.node_id in wanted:
                wanted.update(candidate.dependency_node_ids)
        required = {ancestor for candidate in plan.nodes if candidate.node_id in wanted | {node.node_id}
                    for ancestor in hard_predecessors(plan, candidate)}
        if not required <= accepted.keys():
            raise RuntimeContractError("predecessor has no accepted artifact")
        return tuple(UpstreamExecutionResult(producer_node_id=n.node_id, result=accepted[n.node_id])
                     for n in plan.nodes if n.node_id in wanted and n.node_id in accepted)

    @staticmethod
    def _ready(plan, node, jobs, accepted):
        return set(hard_predecessors(plan, node)) <= accepted.keys() and all(
            ref in accepted or (ref in jobs and jobs[ref].status is JobStatus.FAILED)
            for ref in node.dependency_node_ids)

    @staticmethod
    def _coverage(plan, jobs, accepted):
        if type(plan) is not CompiledExecutionPlanV2:
            return None
        limitations = [{"code": code} for code in plan.limitations]
        failures = [n for n in plan.nodes if optional(n) and n.node_id in jobs
                    and jobs[n.node_id].status is JobStatus.FAILED]
        safe_codes = {"module_blocked", "quality_rejected", "provider_transient", "execution_invalid", "attempts_exhausted"}
        limitations.extend({"code": "optional_node_failed", "node_id": n.node_id,
                            "reason": jobs[n.node_id].error if jobs[n.node_id].error in safe_codes else "execution_invalid"}
                           for n in failures)
        from app.module_registry import ModuleId
        competitors = [n for n in plan.nodes if n.module_id is ModuleId.COMPETITOR_ANALYSIS]
        successful = sum(n.node_id in accepted for n in competitors)
        if competitors and all(n.node_id in accepted or n in failures for n in competitors) and successful == 1:
            limitations.append({"code": "only_one_competitor_analyzed"})
        return {"schema_version": "evidence_coverage.v1", "limitations": limitations,
                "accepted_node_ids": [n.node_id for n in plan.nodes if n.node_id in accepted],
                "competitors_supplied": len(competitors), "competitors_accepted": successful}

    async def _advance_locked(self, session, run):
        if run.status in TERMINAL:
            return []
        revision, plan = await self._plan(session, run.run_id)
        jobs, accepted = await self._graph_state(session, run.run_id, revision, plan)
        if any(n.node_id in jobs and jobs[n.node_id].status is JobStatus.FAILED and not optional(n) for n in plan.nodes):
            run.status, run.error = "failed", "node_failed"
            return []
        coverage = self._coverage(plan, jobs, accepted)
        if coverage is not None:
            run.state_json = coverage
        wake = []
        for node in plan.nodes:
            if node.node_id not in jobs and self._ready(plan, node, jobs, accepted):
                job_id = module_job_id(run.run_id, revision, node.node_id)
                await self.jobs.create_job(session, job_id=job_id, kind=JOB_KIND, marketing_run_id=run.run_id,
                                           workflow_step=node.node_id, payload_json=routing(run.run_id, revision, plan, node))
                session.add(JobExecution(job_id=job_id, available_at=self.clock()))
                wake.append(job_id)
        failed_optional = sum(optional(n) and n.node_id in jobs and jobs[n.node_id].status is JobStatus.FAILED for n in plan.nodes)
        complete = len(accepted) + failed_optional == len(plan.nodes)
        run.status = ("completed_with_limitations" if failed_optional else "completed") if complete else (
            "running" if any(j.status is JobStatus.RUNNING for j in jobs.values()) else "queued")
        if complete:
            run.error = None
        run.updated_at = self.clock().replace(tzinfo=None)
        return wake

    async def advance(self, run_id):
        async with self.sessions() as session, session.begin():
            wake = await self._advance_locked(session, await self._run(session, run_id))
        await self._wake(wake)
        return tuple(wake)

    async def claim(self, job_id=None):
        now = self.clock()
        async with self.sessions() as session, session.begin():
            due = select(Job.job_id).join(JobExecution).where(
                Job.marketing_run_id == MarketingRun.run_id, Job.kind == JOB_KIND,
                Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]), JobExecution.available_at <= now,
                or_(JobExecution.lease_until.is_(None), JobExecution.lease_until <= now),
            )
            if job_id:
                due = due.where(Job.job_id == job_id)
            run = await session.scalar(select(MarketingRun).where(
                MarketingRun.workflow_type == WORKFLOW_TYPE, MarketingRun.status.in_(["queued", "running"]),
                exists(due),
            ).order_by(MarketingRun.created_at, MarketingRun.run_id).with_for_update(skip_locked=True).limit(1))
            if run is None:
                return None
            query = select(JobExecution).join(Job).where(
                Job.marketing_run_id == run.run_id, Job.kind == JOB_KIND,
                Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]), JobExecution.available_at <= now,
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
            if lease.attempts >= self.max_attempts:
                await self._terminal(session, run, job, lease, "attempts_exhausted")
                return None
            lease.attempts += 1
            lease.claim_token, lease.lease_until = uuid.uuid4().hex, now + timedelta(seconds=self.lease_seconds)
            run.status, run.current_step = "running", job.workflow_step
            # Revision comes from immutable routing, validated before external I/O.
            return GraphWorkItem(job.job_id, run.run_id, 1, job.workflow_step, lease.claim_token)

    async def _active(self, session, item):
        run = await self._run(session, item.run_id)
        lease = await session.scalar(select(JobExecution).where(JobExecution.job_id == item.job_id).with_for_update())
        if (run.status in TERMINAL or lease is None or lease.claim_token != item.claim_token
                or lease.lease_until is None or lease.lease_until <= self.clock()):
            return None
        job = await session.get(Job, item.job_id)
        if (job.status is not JobStatus.RUNNING or job.kind != JOB_KIND or job.marketing_run_id != item.run_id
                or job.workflow_step != item.node_id or item.plan_revision != 1
                or item.job_id != module_job_id(item.run_id, item.plan_revision, item.node_id)):
            return None
        return run, job, lease

    async def load_work(self, item):
        async with self.sessions() as session, session.begin():
            if await self._active(session, item) is None:
                return None
            revision, plan = await self._plan(session, item.run_id)
            jobs, accepted = await self._graph_state(session, item.run_id, revision, plan)
            node = next(n for n in plan.nodes if n.node_id == item.node_id)
            if not self._ready(plan, node, jobs, accepted):
                raise RuntimeContractError("dependency barrier is not satisfied")
            upstream = self._upstream(plan, node, accepted)
            packet = node.context_packet
            coverage = self._coverage(plan, jobs, accepted)
            if coverage is not None:
                packet = replace(packet, open_questions=(*packet.open_questions,
                    "Evidence coverage (limitations, not factual claims): " + json.dumps(coverage, sort_keys=True)))
            request = ModuleExecutionRequest(execution_id=item.job_id, module_id=node.module_id,
                objective=node.objective, expected_outputs=node.expected_outputs,
                context_packet=packet, upstream_results=upstream)
            return node.binding, request

    async def finish(self, item, result, quality):
        wake = []
        async with self.sessions() as session, session.begin():
            active = await self._active(session, item)
            if active is None:
                return False
            run, job, lease = active
            revision, plan = await self._plan(session, item.run_id)
            jobs, accepted = await self._graph_state(session, item.run_id, revision, plan)
            node = next(n for n in plan.nodes if n.node_id == item.node_id)
            if not self._ready(plan, node, jobs, accepted):
                raise RuntimeContractError("dependency barrier is not satisfied")
            expected_quality = evaluate_result(item.job_id, result, self._upstream(plan, node, accepted))
            if (result.module_id is not node.module_id or quality != expected_quality
                    or not fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"])
                    or result.normalized_result.module_status is ModuleResultStatus.BLOCKED):
                raise RuntimeContractError("result is not accepted")
            raw = bounded({"schema_version": ARTIFACT_SCHEMA, "run_id": item.run_id, "plan_revision": revision,
                "node_id": node.node_id, "module_id": node.module_id.value,
                "execution_result": result_to_json(result), "quality": quality})
            key = artifact_key(item.run_id, revision, node.node_id)
            session.add(MarketingArtifact(run_id=item.run_id, artifact_key=key, artifact_type=ARTIFACT_SCHEMA,
                                           step=node.node_id, payload_json=raw))
            await self.jobs.transition_job(session, job.job_id, job.version, JobStatus.SUCCEEDED,
                result_json={"artifact_key": key, "artifact_fingerprint": fingerprint(raw), "schema_version": ARTIFACT_SCHEMA})
            lease.claim_token = lease.lease_until = None
            await session.flush()
            wake = await self._advance_locked(session, run)
        await self._wake(wake)
        return True

    async def _terminal(self, session, run, job, lease, code, *, blocked=False, reasons=()):
        await self.jobs.transition_job(session, job.job_id, job.version, JobStatus.FAILED, error=code)
        lease.claim_token = lease.lease_until = None
        try:
            _, plan = await self._plan(session, run.run_id)
        except (ValueError, LookupError, TypeError):
            plan = None  # Corrupt persisted contracts still fail the whole run closed.
        if plan is not None and optional(next((n for n in plan.nodes if n.node_id == job.workflow_step), None)):
            await session.flush()
            try:
                return await self._advance_locked(session, run)
            except RuntimeContractError:
                # Optional provider failure is tolerable; corrupt persisted graph
                # state is not. Retain the canonical failure and stop the run.
                code, blocked = "invalid_persisted_graph", False
        run.status, run.error = ("blocked" if blocked else "failed"), code
        run.state_json = {"failure": {"code": code, "node_id": job.workflow_step, "blocking_reasons": list(reasons)}}
        run.updated_at = self.clock().replace(tzinfo=None)

    async def fail(self, item, *, code, retryable=False, blocking_reasons=()):
        from app.marketing_orchestrator.quality_gates.contracts import BlockingReason
        if code not in {"module_blocked", "quality_rejected", "provider_transient", "execution_invalid"}:
            raise RuntimeContractError("unknown failure code")
        reasons = tuple(sorted(BlockingReason(r).value for r in blocking_reasons))
        wake = []
        async with self.sessions() as session, session.begin():
            active = await self._active(session, item)
            if active is None:
                return False
            run, job, lease = active
            if retryable and code == "provider_transient" and lease.attempts < self.max_attempts:
                lease.claim_token = lease.lease_until = None
                lease.available_at = self.clock() + timedelta(seconds=5 * 2 ** (lease.attempts - 1))
                run.status = "queued"
            else:
                wake = await self._terminal(session, run, job, lease, code, blocked=code == "module_blocked", reasons=reasons)
        await self._wake(wake or [])
        return True
