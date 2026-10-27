"""Owner-scoped saved projects and durable Telegram private-chat context."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import Field
from app.marketing_copilot.api_contracts import ErrorResponse, StrictDTO

from app.security import require_actor
from app.routers.copilot import CopilotRoute
from app.services.project_context_service import ProjectContextService
from app.services.project_history_service import ProjectHistoryService

class ProjectError(ErrorResponse):
    code: Literal["request_conflict", "confirmation_changed", "confirmation_unavailable", "invalid_confirmation",
                  "temporarily_unavailable", "not_found", "invalid_request", "execution_invalid",
                  "stale_context", "discussion_busy"]


class ProjectRoute(CopilotRoute):
    error_model = ProjectError


router = APIRouter(prefix="/projects", tags=["projects-v1"], route_class=ProjectRoute)
PublicID = Annotated[str, Path(min_length=3, max_length=80, pattern=r"^(g:[0-9a-f]{64}|w:[0-9a-f]{32}|t:[1-9][0-9]{0,18}|r:[0-9a-f]{64}|l:chat|c:(0|[1-9][0-9]{0,18}))$")]


class SwitchContext(StrictDTO):
    chat_id: int = Field(gt=0, lt=2**63)
    expected_version: int = Field(ge=0, le=2**63-2)
    public_id: str | None = Field(default=None, min_length=3, max_length=80)
    source_public_id: str | None = Field(default=None, min_length=3, max_length=80)


class SourceDraftMessage(StrictDTO):
    chat_id: int = Field(gt=0, lt=2**63)
    expected_version: int = Field(ge=0, le=2**63-2)
    request_key: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=8000)


class ProjectMessage(StrictDTO):
    chat_id: int = Field(gt=0, lt=2**63)
    expected_version: int = Field(ge=0, le=2**63-2)
    request_key: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=2000)


def service(request: Request):
    api = request.app.state.copilot_api
    history = ProjectHistoryService(api.sessions, graph_reader=api.reader, mentor=api.mentor)
    return ProjectContextService(api.sessions, history, mentor=api.mentor)


@router.get("/history")
async def history(limit: Annotated[int, Query(ge=1, le=50)] = 10,
        offset: Annotated[int, Query(ge=0, le=10000)] = 0,
        source_type: Annotated[str | None, Query(pattern=r"^(graph|workflow|task|receipt|legacy|conversation)$")] = None,
        status: Annotated[str | None, Query(min_length=1, max_length=32)] = None,
        query: Annotated[str | None, Query(max_length=100)] = None,
        actor: int = Depends(require_actor), api=Depends(service)):
    return await api.history.recent(actor, limit=limit, offset=offset, source_type=source_type, status=status, query=query)


@router.get("/items/{public_id}")
async def item(public_id: PublicID, actor: int = Depends(require_actor), api=Depends(service)):
    return await api.history.get(actor, public_id)


@router.get("/items/{public_id}/discussion")
async def discussion(public_id: PublicID, limit: Annotated[int, Query(ge=1, le=50)] = 10,
        offset: Annotated[int, Query(ge=0, le=10000)] = 0,
        actor: int = Depends(require_actor), api=Depends(service)):
    return await api.discussion(actor, public_id, limit=limit, offset=offset)


@router.get("/context")
async def context(chat_id: Annotated[int, Query(gt=0, lt=2**63)], actor: int = Depends(require_actor), api=Depends(service)):
    return await api.current(actor, chat_id)


@router.post("/context")
async def switch(payload: SwitchContext, actor: int = Depends(require_actor), api=Depends(service)):
    return await api.switch(actor, payload.chat_id, payload.expected_version, payload.public_id, payload.source_public_id)


@router.post("/context/messages")
async def message(payload: ProjectMessage, actor: int = Depends(require_actor), api=Depends(service)):
    return await api.message(actor, payload.chat_id, payload.expected_version, payload.request_key, payload.text)


@router.post("/context/draft")
async def source_draft(payload: SourceDraftMessage, actor: int = Depends(require_actor), api=Depends(service)):
    return await api.assemble_draft(actor, payload.chat_id, payload.expected_version, payload.request_key, payload.text)
