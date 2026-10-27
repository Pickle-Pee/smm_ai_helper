"""Durable Telegram ordinary-chat execution receipts.

This is transport idempotency, separate from conversation memory and project
selection. Claims commit before calling the existing chat pipeline. A running or
ambiguous identity is never stolen, including after a process restart.
"""
import asyncio
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db import AsyncSessionLocal
from app.models import ActiveProjectBinding, MarketingRun, ProjectDiscussionTurn, ProjectSession, User
from app.schemas import ChatMessageResponse
from app.marketing_copilot.api_contracts import StrictDTO
from app.marketing_copilot.execution_store import ExecutionStore
from app.marketing_copilot.api_errors import CopilotAPIError, ProviderUnavailable
from app.marketing_copilot.provider_adapters import expected_provider_failure

WORKFLOW_TYPE = "chat_execution.v1"
RETENTION = timedelta(days=30)


def fingerprint(payload, scope):
    wire = payload.model_dump(mode="json") if hasattr(payload, "model_dump") else payload
    try:
        StrictDTO.safe_text(wire)
        encoded = json.dumps({"payload": wire, "scope": scope}, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise CopilotAPIError(422, "invalid_request") from None
    return hashlib.sha256(encoded).hexdigest()


def validated_response(value):
    result = ChatMessageResponse.model_validate(value).model_dump(mode="json")
    StrictDTO.safe_text(result)
    return result


class ChatExecutionService:
    def __init__(self, sessions=AsyncSessionLocal):
        self.sessions = sessions

    @staticmethod
    def identity(actor, request_key):
        return hashlib.sha256(f"{WORKFLOW_TYPE}:{actor}:{request_key}".encode()).hexdigest()

    @staticmethod
    async def _validate_context(db, actor, owner, scope):
        # The caller holds User first, exactly like switch/project/Copilot
        # admission. An absent binding is fenced by that same owner lock.
        binding = await db.scalar(select(ActiveProjectBinding).where(
            ActiveProjectBinding.actor_id == actor,
            ActiveProjectBinding.chat_id == actor).with_for_update())
        if binding is not None and binding.owner_id != owner:
            raise CopilotAPIError(404, "not_found")
        current = f"tg:{actor}:new:{binding.version}" if binding else f"tg:{actor}"
        if (binding is not None and binding.session_id is not None) or current != scope:
            raise CopilotAPIError(409, "stale_context")

    async def admit_unkeyed(self, actor, scope):
        # Compatibility for old HTTP clients: admission still validates context
        # under locks, but without a supplied identity it cannot offer replay.
        async with self.sessions() as db, db.begin():
            await db.execute(insert(User).values(telegram_id=actor).on_conflict_do_nothing(
                index_elements=[User.telegram_id]))
            owner = await db.scalar(select(User.id).where(User.telegram_id == actor).with_for_update())
            await self._validate_context(db, actor, owner, scope)

    async def _claim(self, actor, request_key, mark, scope):
        rid, token = self.identity(actor, request_key), uuid.uuid4().hex
        async with self.sessions() as db, db.begin():
            await db.execute(insert(User).values(telegram_id=actor).on_conflict_do_nothing(
                index_elements=[User.telegram_id]))
            owner = await db.scalar(select(User.id).where(User.telegram_id == actor).with_for_update())
            await self._validate_context(db, actor, owner, scope)
            draft = await db.scalar(select(MarketingRun).where(
                MarketingRun.user_id == owner, MarketingRun.workflow_type == "project_source_draft.v1",
                MarketingRun.state_json["request_key"].astext == request_key))
            if draft is not None and scope != f"tg:{actor}:new:{draft.input_json.get('context_version')}":
                raise CopilotAPIError(409, "stale_context")
            used = await db.scalar(select(ProjectDiscussionTurn.turn_id).join(ProjectSession).where(
                ProjectSession.owner_id == owner, ProjectDiscussionTurn.request_key == request_key).limit(1))
            if used is not None:
                raise CopilotAPIError(409, "request_conflict")
            copilot = await db.get(MarketingRun, ExecutionStore.identity(owner, request_key))
            if copilot is not None and (copilot.user_id != owner or copilot.workflow_type != "copilot_execution.v1"
                    or copilot.status != "completed" or (copilot.state_json or {}).get("response", {}).get("kind") != "CONVERSATION"):
                raise CopilotAPIError(409, "request_conflict")
            won = await db.scalar(insert(MarketingRun).values(run_id=rid, user_id=owner,
                workflow_type=WORKFLOW_TYPE, status="running", input_json={"fingerprint": mark},
                state_json={"token": token}).on_conflict_do_nothing(index_elements=[MarketingRun.run_id])
                .returning(MarketingRun.run_id))
            if won:
                return owner, token, None
            row = await db.scalar(select(MarketingRun).where(MarketingRun.run_id == rid).with_for_update())
            if row.user_id != owner or row.workflow_type != WORKFLOW_TYPE:
                raise CopilotAPIError(409, "request_conflict")
            if row.created_at < datetime.utcnow() - RETENTION:
                # Expired keys are unavailable, never authorization to regenerate.
                # Retention cleanup must retain a tombstone before deleting them.
                raise CopilotAPIError(404, "not_found")
            if row.input_json != {"fingerprint": mark}:
                raise CopilotAPIError(409, "request_conflict")
            if row.status != "completed":
                raise ProviderUnavailable()
            try:
                return owner, None, validated_response(row.state_json["response"])
            except (ValidationError, KeyError, TypeError, ValueError):
                raise ProviderUnavailable() from None

    async def _finish(self, actor, request_key, owner, token, mark, response=None):
        async with self.sessions() as db, db.begin():
            row = await db.scalar(select(MarketingRun).where(
                MarketingRun.run_id == self.identity(actor, request_key), MarketingRun.user_id == owner,
                MarketingRun.workflow_type == WORKFLOW_TYPE).with_for_update())
            if (row is None or row.status != "running" or row.input_json != {"fingerprint": mark}
                    or (row.state_json or {}).get("token") != token):
                raise CopilotAPIError(409, "request_conflict")
            row.status = "completed" if response is not None else "ambiguous"
            row.state_json = {"response": response} if response is not None else {}

    async def execute(self, actor, request_key, payload, scope, operation):
        if (type(actor) is not int or not 0 < actor < 2**63 or not isinstance(request_key, str)
                or len(request_key) > 128
                or not re.fullmatch(rf"tg:{actor}:{actor}:(?:[1-9][0-9]{{0,18}}|action:[0-9a-f]{{32}})", request_key)
                or not isinstance(scope, str)
                or not re.fullmatch(rf"tg:{actor}(?::new:(?:0|[1-9][0-9]{{0,18}}))?", scope)):
            raise CopilotAPIError(422, "invalid_request")
        mark = fingerprint(payload, scope)
        owner, token, replay = await self._claim(actor, request_key, mark, scope)
        if replay is not None:
            return replay
        try:
            response = validated_response(await operation())
        except BaseException as exc:
            await asyncio.shield(self._finish(actor, request_key, owner, token, mark))
            if isinstance(exc, (TimeoutError, ValidationError)) or expected_provider_failure(exc):
                raise ProviderUnavailable() from exc
            raise
        await self._finish(actor, request_key, owner, token, mark, response)
        return response
