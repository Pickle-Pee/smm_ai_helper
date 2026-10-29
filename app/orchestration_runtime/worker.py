"""Durable graph execution; no ingress or context acquisition."""
import asyncio
import logging
import hashlib

import httpx
from sqlalchemy.exc import SQLAlchemyError
from app.llm.telemetry import graph_call_context
from app.llm.openai_text import ModelResponseError, ModelResponseFailureReason

from app.module_execution import ModuleExecutorDispatcher
from app.module_execution.acceptance import fully_accepted
from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.common import ExecutorOutputError
from app.module_registry import ModuleResultStatus
from .errors import RuntimeContractError
from .service import evaluate_result

log = logging.getLogger(__name__)

# Only confirmed empty zero-token anomalies may repeat the unchanged request.
# Ordinary token exhaustion remains terminal, including missing diagnostics.
_MODEL_RESPONSE_RETRYABLE = {
    ModelResponseFailureReason.INCOMPLETE_EMPTY_MAX_OUTPUT_TOKENS: True,
    ModelResponseFailureReason.INCOMPLETE_MAX_OUTPUT_TOKENS: False,
    ModelResponseFailureReason.INCOMPLETE_CONTENT_FILTER: False,
    ModelResponseFailureReason.INCOMPLETE_OTHER: False,
    ModelResponseFailureReason.REFUSAL: False,
    ModelResponseFailureReason.INVALID_ENVELOPE: False,
}


def transient(exc):
    # Project transports may wrap exhausted transient errors in RuntimeError.
    # The wrapper alone is not evidence that retrying is safe/useful.
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, ModelResponseError):
            return _MODEL_RESPONSE_RETRYABLE.get(exc.reason, False)
        if isinstance(exc, (ExecutorOutputError, ModuleExecutionContractError, RuntimeContractError)):
            return False
        if isinstance(exc, (TimeoutError, httpx.TransportError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in {408, 429, 500, 502, 503, 504}
        exc = exc.__cause__
    return False


class ModuleGraphWorker:
    def __init__(self, service, *, timeout_seconds=300):
        if not 0 < timeout_seconds < service.lease_seconds:
            raise ValueError("execution timeout must be shorter than lease")
        self.service = service
        self.dispatcher = ModuleExecutorDispatcher(service.executors)
        self.timeout_seconds = timeout_seconds

    async def once(self, job_id=None):
        item = await self.service.claim(job_id)
        if item is None:
            return False
        log.info("Graph claimed run_id=%s job_id=%s", item.run_id, item.job_id)
        try:
            work = await self.service.load_work(item)
            if work is None:
                return False
            binding, request = work
            hooks = await self.service.provider_hooks(item) if hasattr(self.service, "provider_hooks") else None
            async with asyncio.timeout(self.timeout_seconds) as timeout:
                with graph_call_context(item, request, timeout, hooks):
                    result = await self.dispatcher.dispatch(binding, request)
            if result.normalized_result.module_status is ModuleResultStatus.BLOCKED:
                await self.service.fail(item, code="module_blocked", blocking_reasons=result.normalized_result.blocking_reasons)
                return True
            quality = evaluate_result(item.job_id, result, request.upstream_results)
            if not fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"]):
                await self.service.fail(item, code="quality_rejected")
                return True
            accepted = await self.service.finish(item, result, quality)
            log.info("Graph finish run_id=%s job_id=%s accepted=%s", item.run_id, item.job_id, accepted)
        except SQLAlchemyError:
            # A persistence outage must leave the lease for replacement/recovery.
            raise
        except Exception as exc:
            # Consume a failed attempt explicitly; log only safe type/identity.
            log.error("Graph attempt failed run_id=%s job_id=%s error_type=%s", item.run_id, item.job_id, type(exc).__name__)
            retryable = transient(exc)
            reason = "legacy_retry" if retryable else "legacy_stop"
            try:
                if hasattr(self.service, "retry_decision"):
                    retryable, reason = await self.service.retry_decision(item, exc, retryable)
            except SQLAlchemyError as diagnostic_error:
                log.error("Graph retry decision persistence failed run_id=%s job_id=%s error_type=%s",
                          item.run_id, item.job_id, type(diagnostic_error).__name__)
                exc.add_note("Workflow retry decision persistence failed; lease remains recoverable.")
                raise exc from None
            attempt_id = hashlib.sha256(item.claim_token.encode()).hexdigest()
            log.info("Graph retry decision run_id=%s job_id=%s node_id=%s graph_attempt_id=%s module_execution_id=%s retry_owner=workflow retry_decision=%s usage_state=not_applicable",
                     item.run_id, item.job_id, item.node_id, attempt_id, item.job_id, reason,
                     extra={"job_id": item.job_id, "run_id": item.run_id, "node_id": item.node_id,
                            "graph_attempt_id": attempt_id, "module_execution_id": item.job_id,
                            "retry_owner": "workflow", "retry_decision": reason, "usage_state": "not_applicable"})
            try:
                await self.service.fail(item, code="provider_transient" if retryable else "execution_invalid", retryable=retryable)
            except SQLAlchemyError as persistence_error:
                log.error("Graph failure persistence failed run_id=%s job_id=%s error_type=%s",
                          item.run_id, item.job_id, type(persistence_error).__name__)
                exc.add_note("Workflow failure persistence failed; lease remains recoverable.")
                raise exc from None
        finally:
            try:
                await self.service.release_attempt(item)
            except Exception as exc:
                log.error("Attempt cleanup unavailable lane=graph error_type=%s", type(exc).__name__)
        return True
