from __future__ import annotations

from typing import Any, Dict, List

from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.prompts.assistant_prompts import ASSISTANT_CORE_SYSTEM_PROMPT
from app.agents.utils import safe_json_parse


async def generate_assistant_reply(
    summary: str,
    facts_json: Dict[str, Any],
    last_messages: List[Dict[str, str]],
    last_user_text: str,
    url_summary: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    payload = {
        "summary": summary,
        "facts_json": facts_json,
        "last_messages": last_messages,
        "last_user_text": last_user_text,
        "url_summary": url_summary or {},
    }
    messages = [
        {"role": "system", "content": ASSISTANT_CORE_SYSTEM_PROMPT},
        {"role": "user", "content": f"Input: {payload}"},
    ]
    content, _usage = await openai_chat(
        messages=messages,
        model=settings.DEFAULT_TEXT_MODEL_HARD,
        temperature=0.4,
        max_output_tokens=1200,
    )
    return safe_json_parse(content)
