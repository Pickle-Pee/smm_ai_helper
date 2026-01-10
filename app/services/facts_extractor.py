from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel

from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.prompts.assistant_prompts import FACTS_EXTRACT_SYSTEM_PROMPT
from app.agents.utils import safe_json_parse


class FactsPayload(BaseModel):
    facts: Dict[str, Any]
    conflicts: list[str] = []


FACTS_TEMPLATE = {
    "brand_name": None,
    "product_description": None,
    "offer": None,
    "audience": None,
    "geo": None,
    "language": None,
    "goals": None,
    "tone": None,
    "channels": [],
    "pricing": None,
    "constraints": None,
    "competitors": None,
}


async def extract_facts(
    current_facts: Optional[Dict[str, Any]],
    last_user_message: str,
    url_summary: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    payload = {
        "current_facts": current_facts or FACTS_TEMPLATE,
        "last_user_message": last_user_message,
        "url_summary": url_summary or {},
        "schema": FACTS_TEMPLATE,
    }
    messages = [
        {"role": "system", "content": FACTS_EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": f"Input: {payload}"},
    ]
    content, _usage = await openai_chat(
        messages=messages,
        model=settings.DEFAULT_TEXT_MODEL_LIGHT,
        temperature=0.2,
        max_output_tokens=500,
    )
    data = safe_json_parse(content)
    validated = FactsPayload(**data)
    facts = FACTS_TEMPLATE | (validated.facts or {})
    return {"facts": facts, "conflicts": validated.conflicts}
