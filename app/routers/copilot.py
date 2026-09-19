"""Authenticated, versioned HTTP binding; application work lives in services."""
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.security import require_actor
from app.marketing_copilot.api_contracts import ExecuteRequest, ExecuteResponse, RunResponse, StartedResponse, ErrorResponse
from app.marketing_copilot.api_errors import CopilotAPIError
from app.marketing_copilot.production import build_production_copilot_api


class CopilotRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                # FastAPI's default validation response echoes input values.
                return JSONResponse(status_code=422, content=ErrorResponse(code="invalid_request").model_dump(mode="json"))
            except CopilotAPIError as exc:
                return JSONResponse(status_code=exc.status, content=ErrorResponse(
                    code=exc.code, owned_site=exc.owned_site).model_dump(mode="json"))
        return safe_handler


router = APIRouter(prefix="/copilot", tags=["copilot-v1"], route_class=CopilotRoute,
    responses={status: {"model": ErrorResponse} for status in (404, 409, 422, 503)})


def service(request: Request):
    return request.app.state.copilot_api


def start_copilot_api(app):
    app.state.copilot_api = build_production_copilot_api()


async def close_copilot_api(app):
    await app.state.copilot_api.close()


@router.post("/execute", response_model=ExecuteResponse, responses={202: {"model": StartedResponse}})
async def execute(payload: ExecuteRequest, response: Response, actor: int = Depends(require_actor), api=Depends(service)):
    result = await api.execute(actor, payload)
    if isinstance(result, StartedResponse):
        response.status_code = 202
    return result


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$", max_length=64)],
                  actor: int = Depends(require_actor), api=Depends(service)):
    return await api.reader.get(actor, run_id)
