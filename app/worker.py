"""Run with python -m app.worker. External work never owns a DB transaction."""
import asyncio
from contextlib import AsyncExitStack
import logging
import signal

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db import AsyncSessionLocal
from app.logging import setup_logging
from app.orchestration_runtime.composition import build_production_graph_runtime
from app.workflows.executors import MarketingExecutors, InsufficientSource, InvalidModelOutput
from app.workflows.presentation import delivery_parts
from app.workflows.queue import RedisWakeups, FIXED_WAKEUP_KEY, GRAPH_WAKEUP_KEY
from app.workflows.service import MarketingWorkflowService

log = logging.getLogger(__name__)


def transient_provider_failure(exc):
    """Existing provider adapters wrap exhausted retries in RuntimeError."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, (TimeoutError, httpx.TimeoutException, httpx.NetworkError)):
            return True
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in {408, 429, 500, 502, 503, 504}
        exc = exc.__cause__
    return False


class MarketingWorker:
    def __init__(self, service, executors):
        self.service, self.executors = service, executors

    async def once(self, job_id=None):
        item = await self.service.claim(job_id)
        if item is None:
            return False
        try:
            async with asyncio.timeout(settings.WORKFLOW_TIMEOUT_SECONDS):
                artifact = await self.executors.execute(item)
            await self.service.finish(item, artifact, delivery_parts(artifact))
        except (InsufficientSource, InvalidModelOutput) as exc:
            await self.service.fail(item, retryable=False, message=str(exc))
        except (TimeoutError, httpx.TimeoutException, httpx.NetworkError):
            await self.service.fail(item, retryable=True, message="Провайдер временно недоступен или не ответил вовремя. Создайте новый запрос.")
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code in {408, 429, 500, 502, 503, 504}
            await self.service.fail(item, retryable=retryable, message="Не удалось получить результат от провайдера. Проверьте настройки или создайте новый запрос.")
        except SQLAlchemyError:
            # Leave the lease recoverable when persistence is unavailable.
            raise
        except Exception as exc:
            # Do not persist provider responses, URLs containing credentials or tracebacks.
            log.error("Workflow attempt failed job_id=%s error_type=%s", item.job_id, type(exc).__name__)
            await self.service.fail(item, retryable=transient_provider_failure(exc),
                                    message="Не удалось завершить шаг. Обратитесь к администратору с ID проекта.")
        return True


async def run_lane(worker, queue, *, lane):
    """Every iteration scans PostgreSQL before consulting an expendable hint."""
    while True:
        try:
            if not await worker.once():
                hint = await queue.wait()
                if hint:
                    await worker.once(hint)
        except Exception as exc:
            # Cancellation is BaseException: leave the active lease recoverable.
            log.error("Worker loop unavailable lane=%s error_type=%s", lane, type(exc).__name__)
            await asyncio.sleep(2)


async def main(*, sessions=AsyncSessionLocal, queue_factory=RedisWakeups,
               graph_factory=build_production_graph_runtime, fixed_executor_factory=MarketingExecutors):
    setup_logging()
    loop, task = asyncio.get_running_loop(), asyncio.current_task()
    # Docker sends SIGTERM. TaskGroup cancellation interrupts provider I/O and
    # closes per-call clients without recording a domain failure on shutdown.
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    handles_sigterm = False
    try:
        try:
            loop.add_signal_handler(signal.SIGTERM, task.cancel)
            handles_sigterm = True
        except (NotImplementedError, RuntimeError):
            pass  # Windows/non-main-thread loops use normal task cancellation.
        async with AsyncExitStack() as resources:
            fixed_queue = queue_factory(key=FIXED_WAKEUP_KEY)
            resources.push_async_callback(fixed_queue.close)
            graph_queue = queue_factory(key=GRAPH_WAKEUP_KEY)
            resources.push_async_callback(graph_queue.close)
            service = MarketingWorkflowService(sessions, queue=fixed_queue)
            graph = graph_factory(sessions=sessions, queue=graph_queue, fixed_queue_key=fixed_queue.key)
            log.info("Worker lanes ready fixed=%s graph=%s registry=%s",
                     settings.WORKER_CONCURRENCY, settings.GRAPH_WORKER_CONCURRENCY, graph.metadata.version)
            async with asyncio.TaskGroup() as group:
                for index in range(settings.WORKER_CONCURRENCY):
                    group.create_task(run_lane(MarketingWorker(service, fixed_executor_factory()),
                                               fixed_queue, lane=f"fixed-{index}"))
                for index in range(settings.GRAPH_WORKER_CONCURRENCY):
                    group.create_task(run_lane(graph.create_worker(), graph_queue, lane=f"graph-{index}"))
    finally:
        if handles_sigterm:
            loop.remove_signal_handler(signal.SIGTERM)
            signal.signal(signal.SIGTERM, previous_sigterm)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
