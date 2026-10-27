"""Durable HTTP execution receipts, separate from graph runs and interpretation.

Claims commit before any external work. A crashed/ambiguous claim is never
automatically re-executed: an external provider has no universal exactly-once
contract. Receipts expire after 30 days; keys must not be reused after that window.
Only a NEEDS_INPUT receipt admits a revised payload (the existing clarification
contract). Completed executions are immutable.
"""
import asyncio
from datetime import datetime, timedelta
import hashlib
import json
import uuid

from pydantic import TypeAdapter
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.models import ActiveProjectBinding, MarketingRun, ProjectDiscussionTurn, ProjectSession, User
from .api_contracts import ExecuteResponse
from .api_errors import CopilotAPIError, ProviderUnavailable

WORKFLOW_TYPE = "copilot_execution.v1"
RETENTION = timedelta(days=30)
RESPONSE = TypeAdapter(ExecuteResponse)


def fingerprint(payload):
    # Omitted vs explicitly empty context has defined precedence in this API.
    wire = payload.model_dump(mode="json", exclude_unset=True)
    return hashlib.sha256(json.dumps(wire, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":")).encode()).hexdigest()


class ExecutionStore:
    def __init__(self, sessions, *, wait_seconds=30):
        self.sessions, self.wait_seconds = sessions, wait_seconds

    @staticmethod
    def identity(owner, key):
        return hashlib.sha256(f"{WORKFLOW_TYPE}:{owner}:{key}".encode()).hexdigest()

    async def _validate_admission(self, session, owner, payload, actor):
        # A completed Copilot receipt can delegate CONVERSATION to ordinary
        # chat. The reverse direction must never create a new Copilot execution.
        from app.services.chat_execution_service import ChatExecutionService
        used_chat = await session.get(MarketingRun, ChatExecutionService.identity(actor, payload.request_key))
        if used_chat is not None:
            raise CopilotAPIError(409, "request_conflict")
        version = payload.context_version
        draft = await session.scalar(select(MarketingRun).where(
            MarketingRun.user_id == owner, MarketingRun.workflow_type == "project_source_draft.v1",
            MarketingRun.state_json["request_key"].astext == payload.request_key))
        if draft is not None:
            reserved_version = draft.input_json.get("context_version")
            if version != reserved_version:
                raise CopilotAPIError(409, "stale_context")
        if version is not None:
            binding = await session.scalar(select(ActiveProjectBinding).where(
                ActiveProjectBinding.actor_id == actor, ActiveProjectBinding.chat_id == actor).with_for_update())
            # No binding is the initial inactive epoch zero. The caller holds
            # User, so switch cannot create a binding before this admission commits.
            if binding is None:
                stale = version != 0
            else:
                stale = binding.owner_id != owner or binding.session_id is not None or binding.version != version
            if stale:
                raise CopilotAPIError(409, "stale_context")

    async def claim(self, owner, payload):
        rid, mark, token = self.identity(owner, payload.request_key), fingerprint(payload), uuid.uuid4().hex
        deadline = asyncio.get_running_loop().time() + self.wait_seconds
        while True:
            async with self.sessions() as session, session.begin():
                # One owner lock serializes admissions across Copilot, general
                # chat and selected-project lanes, before any external call.
                actor = await session.scalar(select(User.telegram_id).where(User.id == owner).with_for_update())
                used = await session.scalar(select(ProjectDiscussionTurn.turn_id).join(ProjectSession).where(
                    ProjectSession.owner_id == owner, ProjectDiscussionTurn.request_key == payload.request_key).limit(1))
                if used is not None:
                    raise CopilotAPIError(409, "request_conflict")
                await session.execute(delete(MarketingRun).where(
                    MarketingRun.workflow_type == WORKFLOW_TYPE,
                    MarketingRun.created_at < datetime.utcnow() - RETENTION))
                existing = await session.get(MarketingRun, rid)
                if existing is None or (existing.status == "needs_input" and existing.input_json != {"fingerprint": mark}):
                    await self._validate_admission(session, owner, payload, actor)
                won = await session.scalar(insert(MarketingRun).values(run_id=rid, user_id=owner,
                    workflow_type=WORKFLOW_TYPE, status="running", input_json={"fingerprint": mark},
                    state_json={"token": token}).on_conflict_do_nothing(index_elements=[MarketingRun.run_id])
                    .returning(MarketingRun.run_id))
                if won:
                    return token, None
                row = await session.scalar(select(MarketingRun).where(MarketingRun.run_id == rid)
                                           .with_for_update())
                if row.user_id != owner or row.workflow_type != WORKFLOW_TYPE:
                    raise CopilotAPIError(409, "request_conflict")
                if row.input_json != {"fingerprint": mark}:
                    if row.status != "needs_input":
                        raise CopilotAPIError(409, "request_conflict")
                    row.input_json, row.state_json, row.status = {"fingerprint": mark}, {"token": token}, "running"
                    return token, None
                if row.status in {"completed", "needs_input"}:
                    return None, RESPONSE.validate_python(row.state_json["response"])
                if row.status == "ambiguous":
                    raise ProviderUnavailable()
            if asyncio.get_running_loop().time() >= deadline:
                # The original call may still complete; never steal its claim.
                raise ProviderUnavailable()
            await asyncio.sleep(0.05)

    async def finish(self, owner, payload, token, response=None):
        async with self.sessions() as session, session.begin():
            row = await session.scalar(select(MarketingRun).where(
                MarketingRun.run_id == self.identity(owner, payload.request_key)).with_for_update())
            if (row is None or row.user_id != owner or row.workflow_type != WORKFLOW_TYPE
                    or row.input_json != {"fingerprint": fingerprint(payload)}
                    or row.status != "running" or row.state_json.get("token") != token):
                raise CopilotAPIError(409, "request_conflict")
            if response is None:
                row.status, row.state_json = "ambiguous", {}
            else:
                wire = response.model_dump(mode="json")
                RESPONSE.validate_python(wire)
                row.status = "needs_input" if response.kind == "NEEDS_INPUT" else "completed"
                # Keep the exact fingerprint-only input contract unchanged. Display metadata
                # is immutable receipt state and never becomes model instructions.
                message = getattr(payload, "message", "")
                title = " ".join(message.split())[:140] if isinstance(message, str) else ""
                row.state_json = {"response": wire, "history_title": title or "Сохранённый запрос"}

    async def get(self, owner, key):
        async with self.sessions() as session:
            row = await session.get(MarketingRun, self.identity(owner, key))
            if (row is None or row.user_id != owner or row.workflow_type != WORKFLOW_TYPE
                    or row.created_at < datetime.utcnow() - RETENTION):
                raise CopilotAPIError(404, "not_found")
            if row.status not in {"completed", "needs_input"}:
                raise ProviderUnavailable()
            return RESPONSE.validate_python(row.state_json["response"])

    async def abandon_validation(self, owner, payload, token):
        """Only local confirmation validation failures occur before provider I/O."""
        async with self.sessions() as session, session.begin():
            await session.execute(delete(MarketingRun).where(
                MarketingRun.run_id == self.identity(owner, payload.request_key),
                MarketingRun.user_id == owner, MarketingRun.workflow_type == WORKFLOW_TYPE,
                MarketingRun.status == "running", MarketingRun.state_json["token"].astext == token))
