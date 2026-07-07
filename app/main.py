from pathlib import Path

from fastapi import FastAPI

from app.config import settings
from app.logging import setup_logging
from app.routers import agents_router, tasks_router, images_router, chat_router

setup_logging()

app = FastAPI(title="SMM Swarm API")


@app.on_event("startup")
async def on_startup():
    Path(settings.IMAGE_STORAGE_PATH).mkdir(parents=True, exist_ok=True)


app.include_router(agents_router)
app.include_router(tasks_router)
app.include_router(images_router)
app.include_router(chat_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
