"""Immutable pre-run meaning, scoped to an owner and exact message revision."""
import hashlib
import json

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models import InterpretedRequestRecord
from .contracts import CopilotContractError
from .context_projection import InterpretedRequest, validate_interpreted_request


def message_fingerprint(message: str) -> str:
    if type(message) is not str or not message.strip() or len(message) > 12000:
        raise CopilotContractError("Request must contain 1–12000 characters")
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def validate_interpretation(raw, message: str) -> InterpretedRequest:
    """JSON hydration retains strict enum/tuple parsing and all grounding checks."""
    try:
        result = InterpretedRequest.model_validate_json(json.dumps(raw, allow_nan=False))
        validate_interpreted_request(result, message)
    except (ValidationError, ValueError, TypeError, RecursionError) as exc:
        raise CopilotContractError("Invalid persisted marketing interpretation") from exc
    return result


class InterpretationStore:
    def __init__(self, sessions):
        self.sessions = sessions

    @staticmethod
    def _identity(owner, request_key, message):
        if type(owner) is not int or owner <= 0:
            raise CopilotContractError("Invalid interpretation owner")
        if type(request_key) is not str or not request_key.strip() or len(request_key) > 128:
            raise CopilotContractError("Invalid interpretation request key")
        return owner, request_key, message_fingerprint(message)

    @staticmethod
    def _query(owner, request_key, fingerprint):
        return select(InterpretedRequestRecord.interpretation_json).where(
            InterpretedRequestRecord.owner_id == owner,
            InterpretedRequestRecord.request_key == request_key,
            InterpretedRequestRecord.message_fingerprint == fingerprint,
        )

    async def load(self, owner, request_key, message):
        identity = self._identity(owner, request_key, message)
        async with self.sessions() as session:
            raw = await session.scalar(self._query(*identity))
        return None if raw is None else validate_interpretation(raw, message)

    async def save(self, owner, request_key, message, interpretation):
        owner, request_key, fingerprint = self._identity(owner, request_key, message)
        # Revalidate instances first: model_copy/model_construct must not bypass contracts.
        try:
            interpretation = InterpretedRequest.model_validate(interpretation)
        except (ValidationError, ValueError, TypeError) as exc:
            raise CopilotContractError("Invalid marketing interpretation") from exc
        payload = interpretation.model_dump(mode="json")
        validate_interpretation(payload, message)
        async with self.sessions() as session, session.begin():
            await session.execute(insert(InterpretedRequestRecord).values(
                owner_id=owner, request_key=request_key, message_fingerprint=fingerprint,
                interpretation_json=payload,
            ).on_conflict_do_nothing(index_elements=[
                InterpretedRequestRecord.owner_id, InterpretedRequestRecord.request_key,
                InterpretedRequestRecord.message_fingerprint,
            ]))
            # PostgreSQL READ COMMITTED sees the winner after a competing insert commits.
            raw = await session.scalar(self._query(owner, request_key, fingerprint))
            if raw is None:
                raise CopilotContractError("Persisted marketing interpretation is unavailable")
            return validate_interpretation(raw, message)
