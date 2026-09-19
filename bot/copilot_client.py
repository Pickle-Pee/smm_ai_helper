"""HTTP-only Copilot v1 client. No execution imports or raw error bodies."""
import asyncio
import logging
import re

import httpx
from pydantic import TypeAdapter, ValidationError

from app.config import settings
from bot.backend import actor_headers
from bot import copilot_contracts as dto

log = logging.getLogger(__name__)
RUN_ID = re.compile(r"[0-9a-f]{64}\Z")
EXECUTE_RESPONSE = TypeAdapter(dto.ExecuteResponse)


class CopilotError(Exception):
    def __init__(self, category: str, *, status=None, owned_site=None):
        super().__init__(category)
        self.category, self.status, self.owned_site = category, status, owned_site


class CopilotClient:
    async def _request(self, method, path, actor, *, payload=None):
        try:
            # Total wall-clock bound as well as connect/read/write/pool timeouts.
            async with asyncio.timeout(310), httpx.AsyncClient(timeout=httpx.Timeout(300, connect=10)) as client:
                response = await client.request(method, settings.API_BASE_URL.rstrip("/") + path,
                    headers=actor_headers(actor), json=payload)
        except (httpx.HTTPError, TimeoutError):
            raise CopilotError("unavailable") from None
        if response.status_code >= 400:
            status = response.status_code
            log.warning("Copilot HTTP status=%s actor_id=%s", status, actor)
            category = {401: "auth", 403: "auth", 404: "not_found", 422: "invalid_state",
                        503: "temporary"}.get(status, "server")
            owned = None
            if status == 409:
                try:
                    error = dto.ErrorResponse.model_validate_json(response.content)
                    if error.code in {"confirmation_changed", "request_conflict"}:
                        category, owned = error.code, error.owned_site
                except (ValidationError, ValueError):
                    pass
            raise CopilotError(category, status=status, owned_site=owned)
        return response.content

    async def execute(self, actor: int, payload: dto.ExecuteRequest) -> dto.ExecuteResponse:
        raw = await self._request("POST", "/copilot/execute", actor,
                                  payload=payload.model_dump(mode="json", exclude_unset=True))
        try:
            result = EXECUTE_RESPONSE.validate_json(raw)
        except (ValidationError, ValueError):
            raise CopilotError("invalid_response") from None
        log.info("Copilot actor_id=%s request_key=%s kind=%s run_id=%s", actor,
                 payload.request_key, result.kind, getattr(result, "run_id", None))
        return result

    async def run(self, actor: int, run_id: str) -> dto.RunResponse:
        if not RUN_ID.fullmatch(run_id):
            raise CopilotError("not_found")
        raw = await self._request("GET", f"/copilot/runs/{run_id}", actor)
        try:
            result = dto.RunResponse.model_validate_json(raw)
            if result.run_id != run_id:
                raise ValueError("Mismatched run")
            return result
        except (ValidationError, ValueError):
            raise CopilotError("invalid_response") from None
