import asyncio
import os

import httpx
from fastapi import FastAPI
from pydantic import SecretStr

from app.config import settings
from app.release_barrier import BARRIER_HEADER, ReleaseBarrier


def test_barrier_preserves_admitted_operations_and_fails_closed(tmp_path, monkeypatch):
    file = tmp_path / "admission"
    file.write_bytes(b"open\n")
    token = "release-barrier-token-for-test-only"
    monkeypatch.setattr(settings, "RELEASE_BARRIER_STATE_FILE", str(file))
    monkeypatch.setattr(settings, "RELEASE_BARRIER_TOKEN", SecretStr(token))

    async def run():
        started, finish = asyncio.Event(), asyncio.Event()
        calls = []
        app = FastAPI()
        app.add_middleware(ReleaseBarrier)

        @app.post("/generate")
        async def generate():
            calls.append("provider")
            started.set()
            await finish.wait()
            return {"result": "persisted"}

        @app.get("/ready")
        async def ready():
            return {"status": "ready"}

        status = "/internal/release/barrier"
        telegram = {BARRIER_HEADER: token}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://backend") as client:
            in_flight = asyncio.create_task(client.post("/generate"))
            try:
                await asyncio.wait_for(started.wait(), 2)
                file.write_bytes(b"bot-only\n")
                denied = await client.post("/generate", headers={"Authorization": "Bearer legacy"})
                assert denied.status_code == 503 and denied.headers["Retry-After"] == "30"
                duplicate = [(BARRIER_HEADER, token), (BARRIER_HEADER, token)]
                assert (await client.post("/generate", headers=duplicate)).status_code == 503
                assert (await client.get(status)).status_code == 404
                assert (await client.get(status, headers=telegram)).json() == {
                    "mode": "bot-only", "in_flight": 1, "pid": os.getpid()
                }

                file.unlink()
                assert (await client.post("/generate", headers=telegram)).status_code == 503
                assert (await client.get("/ready")).status_code == 200
                before_release = (await client.get(status, headers=telegram)).json()
                assert before_release["mode"] == "closed" and before_release["in_flight"] == 1

                finish.set()
                assert (await in_flight).json() == {"result": "persisted"}
                assert (await client.get(status, headers=telegram)).json()["in_flight"] == 0
                assert calls == ["provider"]

                file.write_bytes(b"bot-only\n")
                assert (await client.post("/generate", headers=telegram)).status_code == 200
                file.write_bytes(b"open\n")
                assert (await client.post("/generate")).status_code == 200
            finally:
                finish.set()
                await asyncio.gather(in_flight, return_exceptions=True)

    asyncio.run(run())
