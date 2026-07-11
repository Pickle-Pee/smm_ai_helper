from __future__ import annotations

import logging
from typing import Any, Dict, List

from app.services.assistant_core import generate_assistant_reply
from app.services.assistant_normalizer import normalize_assistant_payload
from app.services.qc_shortener import qc_shorten
from app.services.response_policy import enforce_policy


class ChatResponseService:
    """Generates and normalizes assistant responses for chat flows."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(__name__)

    @staticmethod
    def normalize(payload: Dict[str, Any]) -> Dict[str, Any]:
        return normalize_assistant_payload(enforce_policy(payload))

    async def generate(
        self,
        user_message: str,
        summary: str,
        facts_json: Dict[str, Any],
        last_messages: List[Dict[str, str]],
        url_summaries: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        assistant_raw = await generate_assistant_reply(
            user_message=user_message,
            summary=summary,
            facts_json=facts_json,
            last_messages=last_messages,
            url_summaries=url_summaries,
        )
        assistant_policy = enforce_policy(assistant_raw)

        try:
            assistant_qc = await qc_shorten(assistant_policy)
        except Exception:
            self.logger.exception("qc_shorten failed unexpectedly")
            assistant_qc = assistant_policy

        return self.normalize(assistant_qc)
