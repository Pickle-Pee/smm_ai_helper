from __future__ import annotations

from typing import List

from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.prompts.assistant_prompts import SUMMARY_SYSTEM_PROMPT
from app.agents.utils import safe_json_parse


async def update_summary(previous_summary: str, recent_messages: List[dict]) -> str:
    payload = {
        "previous_summary": previous_summary,
        "recent_messages": recent_messages,
    }
    messages = [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": f"Input: {payload}"},
    ]
    content, _usage = await openai_chat(
        messages=messages,
        model=settings.DEFAULT_TEXT_MODEL_LIGHT,
        task="summary",
    )

    data = safe_json_parse(content)
    return data.get("summary", previous_summary)
