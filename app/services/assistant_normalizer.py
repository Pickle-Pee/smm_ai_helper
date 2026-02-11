from __future__ import annotations

import re
from typing import Any, Dict, List


# --- helpers: anti-banal actions + strip questions ---

_BANAL_ACTION_MAP = [
    # (pattern, replacement)
    (r"\bопредел(ить|и)\s+целев(ую|ую)\s+аудитори(ю|я)\b", "Сгенерировать 3 сегмента ЦА + офферы под каждый"),
    (r"\bвыбрат(ь|и)\s+канал(ы|ы)\b", "Собрать медиамикс: 3 канала + что тестируем в каждом"),
    (r"\bназнач(ить|и)\s+бюджет\b", "Сделать 3 сценария бюджета (MIN/MID/MAX) с ожиданиями по метрикам"),
    (r"\bопредел(ить|и)\s+бюджет\b", "Сделать 3 сценария бюджета (MIN/MID/MAX) с ожиданиями по метрикам"),
    (r"\bизуч(ить|и)\s+конкурент(ов|ы)\b", "Разобрать 10 конкурентов: офферы, креативные углы, CTA"),
]

_BANAL_REPLY_PATTERNS = [
    r"\bопредел(ить|и)\s+целев(ую|ую)\s+аудитори(ю|я)\b",
    r"\bвыбрат(ь|и)\s+канал(ы|ы)\b",
    r"\bназнач(ить|и)\s+бюджет\b",
]


def _improve_action_text(text: str) -> str:
    t = (text or "").strip()
    low = t.lower().strip().rstrip(".")
    for pat, repl in _BANAL_ACTION_MAP:
        if re.search(pat, low, flags=re.IGNORECASE):
            return repl
    return t


def _strip_extra_questions(reply: str) -> str:
    """
    Если follow_up_question уже задан, убираем из reply любые дополнительные вопросы,
    чтобы не было “допроса”.

    Удаляем строки, содержащие '?' или начинающиеся с вопросительных слов.
    """
    if not reply:
        return reply

    question_starters = (
        "какой", "какая", "какие", "какого", "каких",
        "сколько", "где", "когда", "почему", "зачем",
        "как", "нужны ли", "нужно ли", "есть ли",
        "в каком", "в каких", "в какой",
    )

    out_lines: List[str] = []
    for line in reply.splitlines():
        l = line.strip()
        if not l:
            out_lines.append(line)
            continue

        low = l.lower()
        if "?" in l:
            continue
        if any(low.startswith(ws) for ws in question_starters):
            continue

        out_lines.append(line)

    cleaned = "\n".join(out_lines).strip()

    # если вдруг reply стал пустым — оставим оригинал (лучше чуть хуже, чем пустота)
    return cleaned or (reply.strip()[:1600])


def normalize_actions(actions: Any) -> List[Dict[str, str]]:
    if not actions:
        return []

    out: List[Dict[str, str]] = []

    if isinstance(actions, list):
        for item in actions:
            if isinstance(item, dict):
                t = str(item.get("type", "suggestion"))
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    out.append({"type": t, "text": _improve_action_text(text)})
            elif isinstance(item, str) and item.strip():
                out.append({"type": "suggestion", "text": _improve_action_text(item)})

    elif isinstance(actions, str) and actions.strip():
        out.append({"type": "suggestion", "text": _improve_action_text(actions)})

    # уберём дубли
    uniq: List[Dict[str, str]] = []
    seen = set()
    for a in out:
        key = (a.get("type", ""), a.get("text", "").lower())
        if key in seen:
            continue
        seen.add(key)
        uniq.append(a)

    return uniq[:4]


def normalize_assistant_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {
            "reply": "",
            "follow_up_question": None,
            "actions": [],
            "intent": "other",
            "assumptions": [],
            "warnings": ["assistant_payload_not_dict"],
        }

    data.setdefault("reply", "")
    data.setdefault("follow_up_question", None)
    data.setdefault("intent", "other")
    data.setdefault("assumptions", [])
    data.setdefault("warnings", [])

    # follow_up_question: только str или None
    fu = data.get("follow_up_question")
    if fu is not None and not isinstance(fu, str):
        data["follow_up_question"] = None
        fu = None

    # actions: нормализация + анти-банальность
    data["actions"] = normalize_actions(data.get("actions"))

    # assumptions/warnings: должны быть списками строк
    for k in ("assumptions", "warnings"):
        v = data.get(k)
        if v is None:
            data[k] = []
        elif isinstance(v, list):
            data[k] = [str(x) for x in v if str(x).strip()][:6]
        else:
            data[k] = [str(v)]

    # intent: только из разрешённых
    allowed = {"content", "strategy", "audit", "ads", "analysis", "other"}
    if data.get("intent") not in allowed:
        data["intent"] = "other"

    # strip extra questions из reply, если follow_up_question уже задан
    if fu and isinstance(data.get("reply"), str):
        data["reply"] = _strip_extra_questions(data["reply"])

    # optional: лёгкий анти-банальный фильтр в reply (не вырезаем, а предупреждаем)
    reply_low = (data.get("reply") or "").lower()
    if any(re.search(p, reply_low) for p in _BANAL_REPLY_PATTERNS):
        # не ломаем текст, просто подскажем в warnings (для отладки)
        data["warnings"] = (data.get("warnings") or []) + ["reply_contains_banal_phrases"]

    return data
