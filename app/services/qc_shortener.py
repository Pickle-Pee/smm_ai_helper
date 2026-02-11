# app/services/qc_shortener.py
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.prompts.assistant_prompts import QC_SYSTEM_PROMPT
from app.services.assistant_normalizer import normalize_assistant_payload

log = logging.getLogger(__name__)


def _fallback_from_raw(raw: Dict[str, Any], reason: str) -> Dict[str, Any]:
    """
    QC не должен ломать выдачу. Возвращаем исходный payload.
    """
    out = dict(raw or {})
    out.setdefault("warnings", [])
    if isinstance(out["warnings"], list):
        out["warnings"].append(f"qc_failed:{reason}")
    else:
        out["warnings"] = [f"qc_failed:{reason}"]
    return normalize_assistant_payload(out)


async def qc_shorten(assistant_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    QC-слой: делает ответ короче/конкретнее.
    Важно: если QC вернул мусор — НЕ падаем, а возвращаем оригинал.
    """
    base = normalize_assistant_payload(assistant_payload)

    # если reply пустой — нет смысла QC-ить
    if not (base.get("reply") or "").strip():
        return base

    # даём модели только то, что она должна вернуть/отредактировать
    payload = {
        "reply": base.get("reply", ""),
        "follow_up_question": base.get("follow_up_question"),
        "actions": base.get("actions", []),
        "assumptions": base.get("assumptions", []),
        "warnings": base.get("warnings", []),
    }

    messages = [
        {"role": "system", "content": QC_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]

    try:
        content, _usage = await openai_chat(
            messages=messages,
            model=settings.DEFAULT_TEXT_MODEL_LIGHT,
            temperature=None,  # важно (у тебя некоторые модели не принимают temperature)
            max_output_tokens=700,
            response_format={"type": "json_object"},  # заставляем JSON-объект
        )
    except Exception as e:
        log.exception("qc_shorten: OpenAI call failed")
        return _fallback_from_raw(base, f"openai_call:{type(e).__name__}")

    # Парсинг: используем обычный json.loads, потому что response_format должен гарантировать объект
    try:
        data = json.loads(content)
        if not isinstance(data, dict):
            return _fallback_from_raw(base, "not_dict")
        # нормализация + страховка по схемам
        data = normalize_assistant_payload(data)
        # если QC случайно “обнулил” ответ — откатываемся
        if not (data.get("reply") or "").strip():
            return _fallback_from_raw(base, "empty_reply")
        return data
    except Exception as e:
        log.error("qc_shorten: JSON parse failed: %s; content=%r", e, content[:8000])
        return _fallback_from_raw(base, f"json_parse:{type(e).__name__}")
