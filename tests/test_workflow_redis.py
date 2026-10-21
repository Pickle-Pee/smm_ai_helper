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


@pytest.mark.skipif(not os.getenv("REDIS_TEST_URL"), reason="REDIS_TEST_URL is not configured")
def test_lane_shutdown_when_cancel_races_with_redis_send_completion():
    from redis.asyncio.connection import Connection, ConnectionPool
    from app.worker import run_lane

    async def exercise():
        injected = asyncio.Event()

        class CancelAtSendCompletion(Connection):
            async def send_packed_command(self, command, **kwargs):
                # Redis uses asyncio.wait_for for socket writes. On Python 3.11
                # a completed write can swallow the caller's simultaneous cancel.
                caller = asyncio.current_task()
                original = self._send_packed_command

                async def send(packed):
                    await original(packed)
                    if b"BLPOP" in b"".join(packed) and not injected.is_set():
                        injected.set()
                        asyncio.get_running_loop().call_soon(caller.cancel)

                self._send_packed_command = send
                try:
                    return await super().send_packed_command(command, **kwargs)
                finally:
                    self._send_packed_command = original

        pool = ConnectionPool.from_url(os.environ["REDIS_TEST_URL"],
            connection_class=CancelAtSendCompletion, decode_responses=True,
            socket_connect_timeout=1, socket_timeout=2)
        wakeups = RedisWakeups(Redis(connection_pool=pool),
            key="smm:test:cancel:" + uuid.uuid4().hex)
        worker = SimpleNamespace(once=AsyncMock(return_value=False))
        task = asyncio.create_task(run_lane(worker, wakeups, lane="fixed-0"))
        try:
            await asyncio.wait_for(injected.wait(), 3)
            done, _ = await asyncio.wait({task}, timeout=3)
            assert task in done, "worker kept scanning after Redis swallowed cancellation"
            with pytest.raises(asyncio.CancelledError):
                await task
            worker.once.assert_awaited_once_with()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await wakeups.close()
            await pool.aclose()

    asyncio.run(exercise())
