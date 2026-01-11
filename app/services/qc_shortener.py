from __future__ import annotations

from typing import Any, Dict

from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.prompts.assistant_prompts import QC_SYSTEM_PROMPT
from app.agents.utils import safe_json_parse


async def qc_shorten(response: Dict[str, Any]) -> Dict[str, Any]:
    payload = {"response": response}
    messages = [
        {"role": "system", "content": QC_SYSTEM_PROMPT},
        {"role": "user", "content": f"Input: {payload}"},
    ]
    content, _usage = await openai_chat(
        messages=messages,
        model=settings.DEFAULT_TEXT_MODEL_LIGHT,
        temperature=0.2,
        max_output_tokens=500,
    )
    return safe_json_parse(content)
