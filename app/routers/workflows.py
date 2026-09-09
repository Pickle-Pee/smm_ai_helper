from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from app.schemas import BrandProfileUpdate
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


@router.post("", status_code=202)
async def start(payload: StartRequest, actor: int = Depends(require_actor)):
    return await call(workflow.start(actor, payload))


@router.get("")
async def recent(actor: int = Depends(require_actor)):
    return await call(workflow.recent(actor))


@router.put("/profile")
async def profile(payload: BrandProfileUpdate, actor: int = Depends(require_actor)):
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(422, "Укажите данные бизнеса.")
    return await call(workflow.set_profile(actor, values))


@router.get("/{run_id}")
async def status(run_id: OpaqueId, actor: int = Depends(require_actor)):
    return await call(workflow.status(actor, run_id))


@router.patch("/{run_id}/context", status_code=202)
async def context(run_id: OpaqueId, payload: BusinessInput, actor: int = Depends(require_actor)):
    return await call(workflow.context(actor, run_id, payload))


@router.post("/{run_id}/continue", status_code=202)
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


@delivery_router.post("/claim")
async def claim_delivery():
    return await delivery.claim()


@delivery_router.post("/{delivery_id}/ack")
async def ack_delivery(delivery_id: OpaqueId, payload: DeliveryAck):
    return {"accepted": await delivery.acknowledge(delivery_id, payload.claim_token,
        message_id=payload.message_id, retryable=payload.retryable, retry_after=payload.retry_after)}
