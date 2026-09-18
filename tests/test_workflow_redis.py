import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError

from app.workflows.queue import RedisWakeups, FIXED_WAKEUP_KEY, GRAPH_WAKEUP_KEY


def test_redis_outage_does_not_fail_a_committed_request():
    class BrokenPipeline:
        async def __aenter__(self): raise ConnectionError("offline")
        async def __aexit__(self, *args): pass
    queue = RedisWakeups(SimpleNamespace(pipeline=lambda **kwargs: BrokenPipeline()))
    asyncio.run(queue.wake("durable-job"))


@pytest.mark.skipif(not os.getenv("REDIS_TEST_URL"), reason="REDIS_TEST_URL is not configured (real Redis integration)")
def test_real_redis_wakeups_duplicates_and_reconnect():
    async def run():
        client = Redis.from_url(os.environ["REDIS_TEST_URL"], decode_responses=True)
        queue = RedisWakeups(client)
        queue.key = "smm:test:marketing:" + uuid.uuid4().hex
        try:
            await queue.wake("same-job")
            await queue.wake("same-job")
            await client.connection_pool.disconnect()
            assert await queue.wait() == "same-job"
            assert await queue.wait() == "same-job"
            assert await queue.wait() is None
        finally:
            await client.delete(queue.key)
            await queue.close()
    asyncio.run(run())


@pytest.mark.skipif(not os.getenv("REDIS_TEST_URL"), reason="REDIS_TEST_URL is not configured")
def test_real_fixed_and_graph_lists_do_not_consume_each_others_hints():
    async def run():
        # Canonical keys in an explicitly disposable Redis database.
        fixed = RedisWakeups(Redis.from_url(os.environ["REDIS_TEST_URL"], decode_responses=True))
        graph = RedisWakeups(Redis.from_url(os.environ["REDIS_TEST_URL"], decode_responses=True), key=GRAPH_WAKEUP_KEY)
        try:
            await fixed.client.delete(FIXED_WAKEUP_KEY, GRAPH_WAKEUP_KEY)
            await fixed.wake("fixed-job")
            assert await graph.wait() is None
            assert await fixed.wait() == "fixed-job"
            await graph.wake("graph-job")
            assert await fixed.wait() is None
            assert await graph.wait() == "graph-job"
        finally:
            await fixed.client.delete(FIXED_WAKEUP_KEY, GRAPH_WAKEUP_KEY)
            await fixed.close()
            await graph.close()
    asyncio.run(run())
