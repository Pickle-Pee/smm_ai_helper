from __future__ import annotations

from typing import Any, Dict

from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.agents.utils import safe_json_parse


class ImageBriefAgent:
    system_prompt = (
        "Ты — арт-директор и продюсер визуальных материалов для SMM. "
        "Отвечай строго JSON без текста до/после."
    )

    async def run(
        self,
        platform: str,
        use_case: str,
        message: str,
        brand: Dict[str, Any] | None,
        overlay_text: Dict[str, str] | None,
    ) -> Dict[str, Any]:
        brand = brand or {}
        overlay_text = overlay_text or {}

        prompt = f"""
Платформа: {platform}
Use case: {use_case}
Сообщение: {message}
Бренд: {brand}
Overlay: {overlay_text}

Верни JSON:
{{
  "mode": "simple|template|hybrid",
  "preset_id": "...",
  "size": "WxH",
  "background_prompt": "NO TEXT, negative space, composition hints",
  "negative_prompt": "...",
  "overlay": {{
    "headline": "...",
    "subtitle": "...",
    "cta": "..."
  }},
  "palette": ["#RRGGBB", "..."],
  "layout": "left|center|bottom",
  "confidence": "low|medium|high"
}}

Правила:
- если есть overlay или use_case баннерный → template
- если пользователь просит текст внутри картинки → hybrid
- иначе → simple
"""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        content, _usage = await openai_chat(
            messages=messages,
            model=settings.DEFAULT_TEXT_MODEL_LIGHT,
            temperature=0.5,
            max_output_tokens=600,
        )
        return safe_json_parse(content)
