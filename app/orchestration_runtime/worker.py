"""Internally runnable graph worker; intentionally not wired into app.worker.main."""
import asyncio
import logging

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.module_execution import ModuleExecutorDispatcher
from app.module_registry import ModuleResultStatus
from .service import evaluate_result

log = logging.getLogger(__name__)


def transient(exc):
    return isinstance(exc, (TimeoutError, httpx.TimeoutException, httpx.NetworkError)) or (
        isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {408, 429, 500, 502, 503, 504})


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
            if result.normalized_result.result_id not in quality["accepted_result_ids"]:
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
