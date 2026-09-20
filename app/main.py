from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import settings
from app.logging import setup_logging
from app.readiness import readiness
from app.services.task_finalization_service import TaskFinalizationUnavailable
from app.routers.workflows import router as workflow_router, delivery_router
from app.routers.copilot import router as copilot_router, start_copilot_api, close_copilot_api
from app.routers import (
    agents_router,
    brand_profile_router,
    chat_router,
    images_router,
    tasks_router,
)

setup_logging()

app = FastAPI(title="SMM Swarm API")


@app.exception_handler(TaskFinalizationUnavailable)
async def task_finalization_unavailable(_request, exc):
    return JSONResponse(status_code=503, content={"detail": str(exc)}, headers={"Retry-After": "5"})


@app.on_event("startup")
async def on_startup():
    if not settings.BOT_BACKEND_TOKEN.strip():
        raise ValueError("Backend requires BOT_BACKEND_TOKEN")
    Path(settings.IMAGE_STORAGE_PATH).mkdir(parents=True, exist_ok=True)
    start_copilot_api(app)


@app.on_event("shutdown")
async def on_shutdown():
    await close_copilot_api(app)


app.include_router(agents_router)
app.include_router(tasks_router)
app.include_router(images_router)
app.include_router(chat_router)
app.include_router(brand_profile_router)
app.include_router(workflow_router)
app.include_router(delivery_router)
app.include_router(copilot_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    ready = await readiness(getattr(app.state, "copilot_api", None))
    return JSONResponse(status_code=200 if ready else 503,
                        content={"status": "ready" if ready else "unavailable"})
