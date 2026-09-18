"""Durable graph execution; no ingress or context acquisition."""
import asyncio
import logging

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.module_execution import ModuleExecutorDispatcher
from app.module_execution.acceptance import fully_accepted
from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.common import ExecutorOutputError
from app.module_registry import ModuleResultStatus
from .errors import RuntimeContractError
from .service import evaluate_result

log = logging.getLogger(__name__)


def transient(exc):
    # Project transports may wrap exhausted transient errors in RuntimeError.
    # The wrapper alone is not evidence that retrying is safe/useful.
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, (ExecutorOutputError, ModuleExecutionContractError, RuntimeContractError)):
            return False
        if isinstance(exc, (TimeoutError, httpx.TimeoutException, httpx.NetworkError)):
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
        try:
            work = await self.service.load_work(item)
            if work is None:
                return False
            binding, request = work
            async with asyncio.timeout(self.timeout_seconds):
                result = await self.dispatcher.dispatch(binding, request)
            if result.normalized_result.module_status is ModuleResultStatus.BLOCKED:
                await self.service.fail(item, code="module_blocked", blocking_reasons=result.normalized_result.blocking_reasons)
                return True
            quality = evaluate_result(item.job_id, result, request.upstream_results)
            if not fully_accepted(result, quality["accepted_result_ids"], quality["accepted_claim_ids"]):
                await self.service.fail(item, code="quality_rejected")
                return True
            await self.service.finish(item, result, quality)
        except SQLAlchemyError:
            # A persistence outage must leave the lease for replacement/recovery.
            raise
        except Exception as exc:
            # Consume a failed attempt explicitly; log only safe type/identity.
            log.error("Graph attempt failed job_id=%s error_type=%s", item.job_id, type(exc).__name__)
            retryable = transient(exc)
            await self.service.fail(item, code="provider_transient" if retryable else "execution_invalid", retryable=retryable)
        return True
