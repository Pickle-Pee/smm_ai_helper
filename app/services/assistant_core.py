# app/services/assistant_core.py
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.prompts.assistant_prompts import ASSISTANT_CORE_SYSTEM_PROMPT
from app.agents.utils import safe_json_parse
from app.services.facts_extractor import extract_facts
from app.services.instagram_intake import parse_instagram_insights
from app.services.strategy_template import is_strategy_like, build_strategy_scaffold
from app.services.url_insights import build_url_insights


def _fallback_assistant_payload(raw_text: str) -> Dict[str, Any]:
    t = (raw_text or "").strip()
    if not t:
        t = "Не смог получить ответ от модели. Попробуй переформулировать запрос в 1–2 предложениях."
    else:
        t = t[:1600]

    return {
        "reply": t,
        "follow_up_question": None,
        "actions": [
            {"type": "suggestion", "text": "Сгенерировать 8 креативных углов под продукт"},
            {"type": "suggestion", "text": "Составить план тестов рекламы на 7 дней"},
        ],
        "intent": "other",
        "assumptions": [],
        "warnings": ["Модель вернула ответ не в JSON-формате — показан текст как есть."],
    }


async def generate_assistant_reply(
    user_message: str,
    summary: str,
    facts_json: Dict[str, Any],
    url_summaries: Optional[List[Dict[str, Any]]] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Основной генератор ответа ассистента.
    Важно:
    - url_summaries: список summaries по ссылкам (до 3)
    - last_messages: реально пробрасываем (до 8)
    """
    last_messages = kwargs.get("last_messages") or []

    # --- 1) intake Instagram инсайтов (если пользователь прислал IG_INSIGHTS)
    ig_intake = parse_instagram_insights(user_message)
    if ig_intake:
        facts_update = await extract_facts(
            current_facts=facts_json or {},
            last_user_message=user_message,
            url_summaries=[],
            url_insights={"manual_instagram_insights": ig_intake},
        )
        # обновляем локальные факты для дальнейшего пайплайна
        facts_json = facts_update.get("facts", facts_json or {})

    # --- 2) нормализация url_summaries
    if not isinstance(url_summaries, list):
        url_summaries = []
    url_summaries = url_summaries[:3]

    # --- 3) LLM-инсайты по ссылкам
    url_insights = None
    if url_summaries:
        try:
            url_insights = await build_url_insights(user_message=user_message, url_summaries=url_summaries)
        except Exception:
            url_insights = None

    # --- 4) обновляем facts из url_context (сайт/тг и т.д.)
    # Это позволяет "помнить" оффер/ЦА/продукт после анализа сайта.
    if url_summaries or url_insights:
        try:
            facts_update = await extract_facts(
                current_facts=facts_json or {},
                last_user_message=user_message,
                url_summaries=url_summaries,
                url_insights=url_insights,
            )
            facts_json = facts_update.get("facts", facts_json or {})
        except Exception:
            pass

    # --- 5) стратегия-шаблон (чтобы не было “допроса” и банальщины)
    scaffold: Optional[str] = None
    if is_strategy_like(user_message):
        chosen_summary: Optional[Dict[str, Any]] = None
        for s in url_summaries:
            if isinstance(s, dict) and s.get("ok") is True:
                chosen_summary = s
                break
        if chosen_summary is None and url_summaries:
            chosen_summary = url_summaries[0]

        scaffold = build_strategy_scaffold(
            user_message=user_message,
            facts_json=facts_json or {},
            url_summary=chosen_summary,
        )

    # --- 6) основной payload ассистента
    payload = {
        "summary": summary,
        "facts_json": facts_json or {},
        "url_summaries": url_summaries,
        "url_insights": url_insights,
        "last_user_message": user_message,
        "last_messages": last_messages[-8:],
        "strategy_scaffold": scaffold,
    }

    messages = [
        {"role": "system", "content": ASSISTANT_CORE_SYSTEM_PROMPT},
        {"role": "user", "content": "INPUT_JSON:\n" + json.dumps(payload, ensure_ascii=False)},
    ]

    content, _usage = await openai_chat(
        messages=messages,
        model=settings.DEFAULT_TEXT_MODEL_LIGHT,
        temperature=None,
        response_format={"type": "json_object"},
        task="copy",
    )

    try:
        data = safe_json_parse(content)
        if not isinstance(data, dict) or "reply" not in data:
            return _fallback_assistant_payload(content)
        return data
    except Exception:
        return _fallback_assistant_payload(content)
