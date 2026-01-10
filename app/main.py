from fastapi import FastAPI

from pathlib import Path

from app.config import settings
from app.db import engine
from app.logging import setup_logging
from app.models import Base
from app.routers import agents_router, tasks_router, images_router

setup_logging()

app = FastAPI(title="SMM Swarm API")


@app.on_event("startup")
async def on_startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Path(settings.IMAGE_STORAGE_PATH).mkdir(parents=True, exist_ok=True)


app.include_router(agents_router)
app.include_router(tasks_router)
app.include_router(images_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
