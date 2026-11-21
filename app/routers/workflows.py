import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.config import settings
from app.db import get_session
from app.schemas import BrandProfileUpdate
from app.services.telegram_onboarding import current_step
from sqlalchemy.exc import SQLAlchemyError
from app.telegram_admission import require_ready_profile
from app.security import require_actor, require_bot
from app.workflows.delivery import DeliveryService
from app.workflows.queue import RedisWakeups
from app.workflows.schemas import BusinessInput, ContinueRequest, StartRequest, Step
from app.workflows.service import MarketingWorkflowService, WorkflowError

router = APIRouter(prefix="/workflows", tags=["marketing-workflow"])
delivery_router = APIRouter(prefix="/internal/delivery", tags=["bot-delivery"], dependencies=[Depends(require_bot)])
workflow = MarketingWorkflowService(queue=RedisWakeups())
delivery = DeliveryService()
OpaqueId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$", max_length=32)]


async def call(operation):
    try:
        return await operation
    except WorkflowError as exc:
        raise HTTPException(exc.status, str(exc)) from exc


@router.post("", status_code=202, dependencies=[Depends(require_ready_profile)])
async def start(payload: StartRequest, actor: int = Depends(require_actor)):
    return await call(workflow.start(actor, payload))


@router.get("")
async def recent(actor: int = Depends(require_actor)):
    return await call(workflow.recent(actor))


class PreferredName(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    replace: bool = False


@router.get("/onboarding")
async def onboarding(actor: int = Depends(require_actor), db=Depends(get_session)):
    if not settings.telegram_onboarding_enabled_for(actor):
        return {"step": "disabled"}
    try:
        step = await current_step(db, actor)
        logging.getLogger("telegram_onboarding").info("event=resume step=%s", step)
        return {"step": step}
    except (SQLAlchemyError, OSError):
        raise HTTPException(503, "temporarily_unavailable") from None


@router.put("/onboarding/name")
async def preferred_name(body: PreferredName, actor: int = Depends(require_actor)):
    if not settings.telegram_onboarding_enabled_for(actor):
        raise HTTPException(404, "Not found")
    if any(ord(char) < 32 for char in body.name):
        raise HTTPException(422, "invalid_request")
    try:
        return {"step": await call(workflow.save_preferred_name(actor, body.name, replace=body.replace))}
    except (SQLAlchemyError, OSError):
        raise HTTPException(503, "temporarily_unavailable") from None


@router.put("/profile")
async def profile(payload: BrandProfileUpdate, actor: int = Depends(require_actor),
                  onboarding_step: Literal["product", "audience", "goal"] | None = None):
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(422, "Укажите данные бизнеса.")
    if onboarding_step is None:
        return await call(workflow.set_profile(actor, values))
    if not settings.telegram_onboarding_enabled_for(actor):
        raise HTTPException(404, "Not found")
    field = {"product": "product_description", "audience": "audience", "goal": "goals"}[onboarding_step]
    value = values.get(field)
    if field == "goals":
        value = value[0] if isinstance(value, list) and len(value) == 1 else None
    if (set(values) != {field} or not isinstance(value, str) or not value.strip()
            or len(value) > 2000 or "\x00" in value):
        raise HTTPException(422, "invalid_request")
    try:
        return await call(workflow.set_profile(actor, values, onboarding_step))
    except (SQLAlchemyError, OSError):
        raise HTTPException(503, "temporarily_unavailable") from None


@router.get("/{run_id}")
async def status(run_id: OpaqueId, actor: int = Depends(require_actor)):
    return await call(workflow.status(actor, run_id))


@router.patch("/{run_id}/context", status_code=202, dependencies=[Depends(require_ready_profile)])
async def context(run_id: OpaqueId, payload: BusinessInput, actor: int = Depends(require_actor)):
    return await call(workflow.context(actor, run_id, payload))


@router.post("/{run_id}/continue", status_code=202, dependencies=[Depends(require_ready_profile)])
async def continue_run(run_id: OpaqueId, payload: ContinueRequest, actor: int = Depends(require_actor)):
    return await call(workflow.continue_run(actor, run_id, payload.action))


@router.get("/{run_id}/artifacts/{step}")
async def artifact(run_id: OpaqueId, step: Step, actor: int = Depends(require_actor)):
    result = await call(workflow.status(actor, run_id))
    if step not in result["artifacts"]:
        raise HTTPException(404, "Результат ещё не готов.")
    return result["artifacts"][step]


@router.get("/{run_id}/jobs/{job_id}")
async def job(run_id: OpaqueId, job_id: OpaqueId, actor: int = Depends(require_actor)):
    result = await call(workflow.status(actor, run_id))
    for item in result["jobs"]:
        if item["job_id"] == job_id:
            return item
    raise HTTPException(404, "Задание не найдено.")


@router.post("/{run_id}/delivery/retry")
async def retry_delivery(run_id: OpaqueId, actor: int = Depends(require_actor)):
    return await call(workflow.retry_delivery(actor, run_id))


class DeliveryAck(BaseModel):
    claim_token: str = Field(pattern=r"^[0-9a-f]{32}$")
    message_id: int | None = Field(default=None, ge=1, lt=2**63)
    retryable: bool = True
    retry_after: int = Field(default=0, ge=0, le=3600)
    sent_parts: int | None = Field(default=None, ge=0, le=256)


@delivery_router.post("/claim")
async def claim_delivery():
    return await delivery.claim()


@delivery_router.post("/{delivery_id}/ack")
async def ack_delivery(delivery_id: OpaqueId, payload: DeliveryAck):
    return {"accepted": await delivery.acknowledge(delivery_id, payload.claim_token,
        message_id=payload.message_id, retryable=payload.retryable, retry_after=payload.retry_after,
        sent_parts=payload.sent_parts)}
