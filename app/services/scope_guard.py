from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Tuple

from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.services.url_analyzer import extract_urls


# ------------- Быстрый слой (без LLM) -------------

MARKETING_KEYWORDS = [
    # общее
    "маркет", "маркетинг", "продвиж", "реклам", "смм", "smm", "таргет",
    "лиды", "лид", "заявк", "продаж", "воронк", "конверси", "cpa", "cpc", "cpm", "ctr", "roi", "romi",
    "бренд", "позиционирован", "утп", "оффер", "цена", "прайс", "аудитория", "ца",
    "контент", "контент-план", "пост", "рилс", "reels", "сторис", "stories", "креатив", "баннер",
    "seo", "асо", "aso", "лендинг", "landing", "сайт",
    # соцсети
    "инст", "instagram", "vk", "вк", "telegram", "tg", "ютуб", "youtube", "tiktok", "тик", "dzen", "дзен",
    # задачи
    "стратег", "анализ", "аналит", "метрик", "отчёт", "кампан", "ads",
]

OFFTOPIC_KEYWORDS = [
    # “явно не маркетинг”
    "реши задачу", "математ", "код", "python", "sql", "реферат", "сочинение",
    "психолог", "медицин", "диагноз", "лекарств", "юрид", "договор",
    "гороскоп", "астролог",
]

def _looks_like_marketing(text: str) -> bool:
    t = (text or "").lower()

    # если есть ссылка — чаще всего это “аудит/разбор” (в теме)
    if extract_urls(t):
        return True

    # явные маркетинговые слова
    if any(k in t for k in MARKETING_KEYWORDS):
        return True

    return False


def _looks_strongly_offtopic(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in OFFTOPIC_KEYWORDS)


def _scope_block_payload(user_text: str) -> Dict[str, Any]:
    return {
        "reply": (
            "Я помогаю только с маркетингом/СММ: стратегия, контент, реклама, аудит, аналитика.\n\n"
            "Сформулируй запрос в этом контексте — например:\n"
            "• «Сделай стратегию продвижения для …»\n"
            "• «Разбери мой сайт/аккаунт и дай рекомендации»\n"
            "• «Напиши рекламный пост/оффер для …»"
        ),
        "follow_up_question": "Что именно нужно: стратегия, контент, реклама или аудит?",
        "actions": [
            {"type": "suggestion", "text": "Сделать стратегию продвижения"},
            {"type": "suggestion", "text": "Разобрать сайт/соцсеть по ссылке"},
            {"type": "suggestion", "text": "Сделать контент-план на 14 дней"},
            {"type": "suggestion", "text": "Сгенерировать рекламный пост/креатив"},
        ],
        "intent": "other",
        "assumptions": [],
        "warnings": ["out_of_scope_request"],
    }


# ------------- Точный слой (LLM-классификатор) -------------

SCOPE_CLASSIFIER_PROMPT = """Ты — классификатор запросов.
Определи, относится ли сообщение пользователя к маркетингу/СММ/продвижению (включая аудит сайта/соцсетей, рекламу, контент, аналитику).

Верни строго JSON:
{
  "in_scope": true|false,
  "reason": "коротко почему",
  "suggested_marketing_reframe": "если не в теме — как переформулировать в маркетинговый запрос"
}
"""

async def scope_guard(
    user_text: str,
    *,
    use_llm_fallback: bool = True,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Возвращает:
    - (True, None) если пропускаем
    - (False, assistant_payload) если блокируем
    """

    if not user_text or not user_text.strip():
        return True, None

    # 1) если явно “не маркетинг” — блокируем сразу
    if _looks_strongly_offtopic(user_text) and not _looks_like_marketing(user_text):
        return False, _scope_block_payload(user_text)

    # 2) если явно “маркетинг” — пропускаем
    if _looks_like_marketing(user_text):
        return True, None

    # 3) пограничный случай — спросим классификатор (опционально)
    if not use_llm_fallback:
        return False, _scope_block_payload(user_text)

    messages = [
        {"role": "system", "content": SCOPE_CLASSIFIER_PROMPT},
        {"role": "user", "content": json.dumps({"user_text": user_text}, ensure_ascii=False)},
    ]

    try:
        content, _usage = await openai_chat(
            messages=messages,
            model=settings.DEFAULT_TEXT_MODEL_LIGHT,
            temperature=None,  # важно для gpt-5-mini и др.
            max_output_tokens=200,
            response_format={"type": "json_object"},
        )
        data = json.loads(content)
        in_scope = bool(data.get("in_scope", False))
        if in_scope:
            return True, None

        # не в теме — мягко редиректим (с рефреймом, если есть)
        ref = (data.get("suggested_marketing_reframe") or "").strip()
        payload = _scope_block_payload(user_text)
        if ref:
            payload["reply"] = payload["reply"] + "\n\nНапример так:\n• " + ref
        return False, payload

    except Exception:
        # если классификатор упал — лучше мягко блокнуть, чем отдать “про всё”
        return False, _scope_block_payload(user_text)
