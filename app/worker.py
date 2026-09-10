"""Run with python -m app.worker. External work never owns a DB transaction."""
import asyncio
import logging

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.workflows.executors import MarketingExecutors, InsufficientSource, InvalidModelOutput
from app.workflows.presentation import delivery_parts
from app.workflows.queue import RedisWakeups
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


async def main():
    logging.basicConfig(level=logging.INFO)
    queue = RedisWakeups()
    service = MarketingWorkflowService(queue=queue)
    async def lane():
        worker = MarketingWorker(service, MarketingExecutors())
        while True:
            try:
                if not await worker.once():
                    hint = await queue.wait()
                    if hint:
                        await worker.once(hint)
            except Exception as exc:
                # DB outages leave leases durable and recoverable.
                log.error("Worker loop unavailable error_type=%s", type(exc).__name__)
                await asyncio.sleep(2)
    try:
        async with asyncio.TaskGroup() as group:
            for _ in range(settings.WORKER_CONCURRENCY):
                group.create_task(lane())
    finally:
        await queue.close()


if __name__ == "__main__":
    asyncio.run(main())
