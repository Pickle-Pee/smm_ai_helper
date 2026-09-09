"""Redis wakeups are expendable. PostgreSQL due scans recover all work."""
import asyncio
import logging

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings

log = logging.getLogger(__name__)


class RedisWakeups:
    key = "smm:marketing:wakeups:v1"

    def __init__(self, client=None):
        self.client = client or Redis.from_url(settings.REDIS_URL, decode_responses=True,
                                               socket_connect_timeout=1, socket_timeout=2)

    async def wake(self, job_id):
        try:
            async with self.client.pipeline(transaction=True) as pipe:
                await pipe.rpush(self.key, job_id).ltrim(self.key, -10000, -1).execute()
        except (RedisError, OSError):
            log.debug("Redis wakeup unavailable; durable scan will recover")

    async def wait(self):
        try:
            value = await self.client.blpop(self.key, timeout=1)
            return value[1] if value else None
        except (RedisError, OSError):
            await asyncio.sleep(1)
            return None

    async def close(self):
        await self.client.aclose()
