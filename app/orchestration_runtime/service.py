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
from app.models import Job, JobExecution, JobStatus, MarketingArtifact, MarketingRun, OrchestrationPlanRecord, PositioningVerification, User
from app.services.job_persistence_service import JobPersistenceService
from app.services.worker_drain_service import claim_admitted, record_attempt, end_attempt, release_attempt
from app.module_execution import ModuleExecutionRequest, UpstreamExecutionResult
from app.module_execution.acceptance import fully_accepted
from app.marketing_orchestrator.quality_gates import QualityGateEvaluator
from app.marketing_orchestrator.quality_gates.contracts import EvaluationBatch
from app.module_registry import ModuleId, ModuleResultStatus
from .compiler import validate_compiled_plan
from .contracts import ARTIFACT_SCHEMA, JOB_KIND, WORKFLOW_TYPE, GraphWorkItem, artifact_key, module_job_id, validate_identity, optional, hard_predecessors, CompiledExecutionPlanV2
from .errors import RuntimeContractError, StartIdentityConflict
from .retry_policy import RetryGovernanceError, new_policy, reserve, complete, decision
from .serialization import bounded, fingerprint, plan_from_json, plan_to_json, result_from_json, result_to_json

log = logging.getLogger(__name__)
VERIFICATION_OPERATION = "positioning_verification.v1"
TERMINAL = {"completed", "completed_with_limitations", "blocked", "failed"}


def utcnow():
    return datetime.now(timezone.utc)


def history_title(plan):
    """Small immutable display metadata from explicit saved facts; no model call."""
    labels = {"strategy_builder_v1": "Стратегия продвижения",
              "competitive_positioning_v1": "Анализ конкурентов"}
    title = labels.get(plan.scenario_key, "Маркетинговый запрос")
    for node in plan.nodes:
        for fact in (*node.context_packet.relevant_project_context, *node.context_packet.known_facts):
            if fact.label == "product" and isinstance(fact.value, str) and fact.value.strip():
                return title + " — " + " ".join(fact.value.split())[:100]
    return title


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
                 lease_seconds=330, max_attempts=3, responses_governance=False, responses_output_budget=192000, positioning_verifier=None):
        if lease_seconds <= 0 or not 1 <= max_attempts <= 10:
            raise ValueError("invalid execution policy")
        self.sessions, self.executors, self.queue, self.clock = sessions, executors, queue, clock
        self.lease_seconds, self.max_attempts = lease_seconds, max_attempts
        self.jobs = JobPersistenceService(clock)
        if type(responses_output_budget) is not int or not 1 <= responses_output_budget <= 1000000:
            raise ValueError("invalid Responses output budget")
        if positioning_verifier is not None and not responses_governance:
            raise ValueError("POSITIONING verification requires Responses governance")
        self.positioning_verifier = positioning_verifier
        self.responses_governance = responses_governance
        self.responses_output_budget = responses_output_budget

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
                input_json={
                    "history_title": history_title(plan),
                    **({"positioning_verification": VERIFICATION_OPERATION}
                       if self.positioning_verifier is not None else {}),
                    **({"responses_retry": new_policy(len(plan.nodes), self.responses_output_budget)}
                       if self.responses_governance else {}),
                }, state_json={},
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
            run = await session.get(MarketingRun, run_id) if node.module_id is ModuleId.POSITIONING else None
            if run is not None and self._verification_required(run, job):
                checkpoint = await session.get(PositioningVerification, job.job_id)
                if (checkpoint is None or checkpoint.state != "verified"
                        or checkpoint.checkpoint.get("draft", {}).get("result") != raw["execution_result"]):
                    raise RuntimeContractError("POSITIONING artifact lacks verification")
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
        async with self.sessions() as session, session.begin():
            if not await claim_admitted(session):
                return None
            now = self.clock()
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
            record_attempt(session, job.job_id, lease.claim_token)
            run.status, run.current_step = "running", job.workflow_step
            # Revision comes from immutable routing, validated before external I/O.
            return GraphWorkItem(job.job_id, run.run_id, 1, job.workflow_step, lease.claim_token, lease.attempts)

    async def release_attempt(self, item):
        await release_attempt(self.sessions, item.job_id, item.claim_token)

    @staticmethod
    def _verification_required(run, job):
        return (run.input_json.get("positioning_verification") == VERIFICATION_OPERATION
                and job.payload_json.get("module_id") == ModuleId.POSITIONING.value)

    async def provider_hooks(self, item, *, verification=False):
        async with self.sessions() as session, session.begin():
            active = await self._active(session, item)
            if active is None:
                raise RetryGovernanceError("inactive_graph_attempt")
            run, job, _ = active
            checkpointed = self._verification_required(run, job)
            if "responses_retry" not in run.input_json:
                return None
        if verification and not checkpointed:
            raise RetryGovernanceError("verification_not_enabled")
        operation = VERIFICATION_OPERATION if verification else None

        async def before(fields):
            await self._provider_receipt(item, fields, finished=False, operation=operation)

        async def after(fields, text=None, payload=None):
            await self._provider_receipt(item, fields, finished=True, operation=operation,
                                         response_text=text, payload=payload)

        if not checkpointed:
            return before, after

        async def replay(payload):
            async with self.sessions() as session, session.begin():
                if await self._active(session, item) is None:
                    raise RetryGovernanceError("inactive_graph_attempt")
                row = await session.get(PositioningVerification, item.job_id)
                saved = row.checkpoint.get("verification" if verification else "generation") if row else None
                if saved is None:
                    return None
                if saved["request_fingerprint"] != fingerprint(payload):
                    raise RetryGovernanceError("checkpoint_request_mismatch")
                return saved["text"]

        return before, after, replay

    async def _provider_receipt(self, item, fields, *, finished, operation=None,
                                response_text=None, payload=None):
        # Lock run -> lease -> Job before reserving or storing private state.
        names = ("provider_call_id", "graph_attempt_id", "graph_attempt", "module_execution_id",
                 "node_id", "model", "schema_fingerprint", "max_output_tokens", "retry_owner", "retry_decision")
        if finished:
            names += ("outcome", "outcome_unknown", "status", "request_id", "response_id", "incomplete_reason", "failure_reason",
                      "usage_state", "token_usage_state", "input_tokens", "output_tokens", "reasoning_tokens",
                      "input_tokens_usage_state", "output_tokens_usage_state", "reasoning_tokens_usage_state", "duration_ms", "http_status")
        receipt = {name: fields[name] for name in names if name in fields}
        async with self.sessions() as session, session.begin():
            active = await self._active(session, item)
            if active is None:
                raise RetryGovernanceError("inactive_graph_attempt")
            run, job, _ = active
            checkpointed = self._verification_required(run, job)
            row = await session.get(PositioningVerification, item.job_id) if checkpointed else None
            if operation is not None:
                if operation != VERIFICATION_OPERATION or row is None or row.state != "verifying":
                    raise RetryGovernanceError("verification_checkpoint_not_ready")
                receipt["operation"] = operation
            policy = run.input_json["responses_retry"]
            updated = complete(policy, receipt) if finished else reserve(policy, receipt)
            if checkpointed and finished and receipt["outcome"] == "success":
                if type(response_text) is not str or not 0 < len(response_text) <= 131072 or payload is None:
                    raise RetryGovernanceError("invalid_checkpoint_response")
                if row is None:
                    row = PositioningVerification(job_id=item.job_id, state="draft_persisted",
                                                  checkpoint={}, updated_at=self.clock())
                    session.add(row)
                key = "verification" if operation else "generation"
                row.checkpoint = bounded({**row.checkpoint, key: {
                    "request_fingerprint": fingerprint(payload), "text": response_text,
                    "receipt": receipt, "plan_revision": item.plan_revision,
                }})
                row.updated_at = self.clock()
            run.input_json = {**run.input_json, "responses_retry": updated}

    async def verification_draft(self, item, result, evidence):
        async with self.sessions() as session, session.begin():
            active = await self._active(session, item)
            if active is None:
                raise RuntimeContractError("inactive_graph_attempt")
            run, job, _ = active
            if not self._verification_required(run, job):
                return False
            row = await session.get(PositioningVerification, item.job_id)
            if row is None or row.state not in {"draft_persisted", "verifying", "verified"}:
                raise RuntimeContractError("verification draft unavailable")
            draft = bounded({"result": result_to_json(result), "evidence": evidence,
                             "contract": VERIFICATION_OPERATION})
            digest = fingerprint(draft)
            if "draft_fingerprint" in row.checkpoint and row.checkpoint["draft_fingerprint"] != digest:
                raise RuntimeContractError("verification draft mismatch")
            if row.state != "verified":
                row.state = "verifying"
                row.checkpoint = bounded({**row.checkpoint, "draft": draft, "draft_fingerprint": digest})
                row.updated_at = self.clock()
            return True

    async def record_verification(self, item, decision):
        async with self.sessions() as session, session.begin():
            if await self._active(session, item) is None:
                raise RuntimeContractError("inactive_graph_attempt")
            row = await session.get(PositioningVerification, item.job_id)
            if (row is None or row.state not in {"verifying", "verified"}
                    or "verification" not in row.checkpoint
                    or decision.get("status") not in {"verified", "rejected", "blocked"}):
                raise RuntimeContractError("invalid verification decision")
            if row.state == "verified" and row.checkpoint["decision"] != decision:
                raise RuntimeContractError("verified decision changed")
            row.state = decision["status"]
            row.checkpoint = bounded({**row.checkpoint, "decision": decision})
            row.updated_at = self.clock()

    async def retry_decision(self, item, exc, legacy_retryable):
        async with self.sessions() as session, session.begin():
            active = await self._active(session, item)
            if active is None:
                return False, "stop_inactive_attempt"
            run, _job, lease = active
            policy = run.input_json.get("responses_retry")
            if policy is None:
                return legacy_retryable, "legacy_retry" if legacy_retryable else "legacy_stop"
            retryable, reason = decision(exc)
            calls = [c for c in policy["calls"] if c["node_id"] == item.node_id]
            if any(c["outcome"] in {"reserved", "unknown", "success"} for c in calls):
                retryable, reason = False, "stop_unknown_or_completed_call"
            elif (lease.attempts >= self.max_attempts or len(calls) >= policy["max_node_calls"]
                  or len(policy["calls"]) >= policy["max_calls"]
                  or sum(c["max_output_tokens"] for c in policy["calls"]) >= policy["max_output_tokens"]):
                retryable, reason = False, "stop_retry_exhausted"
            updated_calls = [{**c, "retry_decision": reason} if c["node_id"] == item.node_id
                             and c.get("graph_attempt") == item.attempt else c for c in policy["calls"]]
            run.input_json = {**run.input_json, "responses_retry": {**policy, "calls": updated_calls, "last_retry_decision": reason}}
            return retryable, reason

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
            await end_attempt(session, item.job_id, item.claim_token)
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
            if self._verification_required(run, job):
                row = await session.get(PositioningVerification, item.job_id)
                if (row is None or row.state != "verified"
                        or row.checkpoint["draft"]["result"] != result_to_json(result)):
                    raise RuntimeContractError("POSITIONING has no verified draft")
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
        if self._verification_required(run, job):
            checkpoint = await session.get(PositioningVerification, job.job_id)
            if checkpoint is None:
                session.add(PositioningVerification(job_id=job.job_id, state="blocked",
                    checkpoint={"reason": code}, updated_at=self.clock()))
            elif checkpoint.state not in {"rejected", "blocked"}:
                checkpoint.state = "blocked"
                checkpoint.checkpoint = {**checkpoint.checkpoint, "reason": code}
                checkpoint.updated_at = self.clock()
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
            await end_attempt(session, item.job_id, item.claim_token)
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
