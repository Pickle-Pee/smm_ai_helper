from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from asyncpg import NonUniqueKeysInAJsonObjectError
from pydantic import BaseModel, Field

from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.prompts.assistant_prompts import FACTS_EXTRACT_SYSTEM_PROMPT
from app.agents.utils import safe_json_parse
import json


class FactsPayload(BaseModel):
    # делаем не обязательным + безопасный дефолт
    facts: Dict[str, Any] = Field(default_factory=dict)
    conflicts: list[str] = Field(default_factory=list)


FACTS_TEMPLATE: Dict[str, Any] = {
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
    "instagram_intake": None
}


def _coerce_conflicts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    # если модель вернула dict (как в твоей ошибке) — считаем что конфликтов нет
    if isinstance(value, dict):
        return []
    return [str(value)]


def _extract_top_level_facts(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Если LLM вернула факты НЕ внутри поля facts, а на верхнем уровне —
    аккуратно собираем только ключи из FACTS_TEMPLATE.
    """
    out: Dict[str, Any] = {}
    for k in FACTS_TEMPLATE.keys():
        if k in data:
            out[k] = data.get(k)
    return out


def _normalize_llm_payload(raw: Any) -> Tuple[Dict[str, Any], list[str]]:
    """
    Приводим ответ модели к виду:
    {
      "facts": {...},
      "conflicts": [...]
    }
    """
    if not isinstance(raw, dict):
        return {}, []

    # 1) conflicts
    conflicts = _coerce_conflicts(raw.get("conflicts"))

    # 2) facts
    facts = raw.get("facts")
    if isinstance(facts, dict):
        facts_dict = facts
    else:
        # если facts нет или он не dict — пробуем собрать с верхнего уровня
        facts_dict = _extract_top_level_facts(raw)

    # 3) отфильтруем только разрешённые ключи
    facts_dict = {k: facts_dict.get(k) for k in FACTS_TEMPLATE.keys()}

    return facts_dict, conflicts


async def extract_facts(
    current_facts: Optional[Dict[str, Any]],
    last_user_message: str,
    url_summaries: list[dict] | None = None,
    url_insights: dict | None = None,
) -> Dict[str, Any]:
    compact_url_summaries = []
    for s in (url_summaries or [])[:3]:
        if not isinstance(s, dict):
            continue
        compact_url_summaries.append(
            {
                "url": s.get("final_url") or s.get("url"),
                "page_type": s.get("page_type"),
                "ok": bool(s.get("ok")),
                "status_code": s.get("status_code"),
                "title": s.get("title"),
                "meta_description": s.get("meta_description"),
                "h1": s.get("h1"),
                "cta_texts": s.get("cta_texts"),
                "warnings": s.get("warnings") or [],
            }
        )

    payload = {
        "current_facts": current_facts or FACTS_TEMPLATE,
        "last_user_message": last_user_message,
        "schema": FACTS_TEMPLATE,
        "url_context": {
            "url_insights": url_insights,  # <-- главное
            "url_summaries": compact_url_summaries  # <-- fallback
        },
    }

    messages = [
        {"role": "system", "content": FACTS_EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": "INPUT_JSON:\n" + json.dumps(payload, ensure_ascii=False)},
    ]

    content, _usage = await openai_chat(
        messages=messages,
        model=settings.DEFAULT_TEXT_MODEL_LIGHT,
        response_format={"type": "json_object"},
        task="facts_json",
    )

    data = safe_json_parse(content)

    facts_dict, conflicts = _normalize_llm_payload(data)
    validated = FactsPayload(facts=facts_dict, conflicts=conflicts)

    # Мерж: дефолты + текущие факты + новые факты
    base = dict(FACTS_TEMPLATE)
    base.update(current_facts or {})
    base.update(validated.facts or {})

    # Нормализация channels (чтобы не было None/строки)
    ch = base.get("channels")
    if ch is None:
        base["channels"] = []
    elif isinstance(ch, str):
        base["channels"] = [x.strip() for x in ch.split(",") if x.strip()]
    elif isinstance(ch, list):
        base["channels"] = [str(x).strip() for x in ch if str(x).strip()]
    else:
        base["channels"] = [str(ch).strip()] if str(ch).strip() else []

    return {"facts": base, "conflicts": validated.conflicts}
