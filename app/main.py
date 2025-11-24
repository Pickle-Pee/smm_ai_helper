from fastapi import FastAPI

from app.db import engine
from app.logging import setup_logging
from app.models import Base
from app.routers import agents_router, tasks_router

setup_logging()

app = FastAPI(title="SMM Swarm API")


@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


app.include_router(agents_router)
app.include_router(tasks_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
