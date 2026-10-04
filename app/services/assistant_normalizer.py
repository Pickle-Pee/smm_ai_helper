from __future__ import annotations

import re
from typing import Any, Dict, List


# Recognize formatting only at delimiter boundaries; URLs and HTML stay literal.
_URL_OR_HTML = re.compile(r"(?<![a-zA-Z0-9+.-])[a-zA-Z][a-zA-Z0-9+.-]*://[^\s<>]+|<[^<>\n]+>")
_HEADING = re.compile(r"(?m)^( {0,3})#{1,6}[ \t]+([^\n]+)$")
_EMPHASIS = re.compile(
    r"(?<![\w*])\*\*(?!\s)([^*\n]*?\S)\*\*(?![\w*])"
    r"|(?<![\w_])__(?!\s)([^_\n]*?\S)__(?![\w_])"
    r"|(?<![\w*])\*(?![\s*])([^*\n]*?\S)\*(?![\w*])"
    r"|(?<![\w_])_(?![\s_])([^_\n]*?\S)_(?![\w_])"
    r"|(?<!`)`([^`\n]+)`(?!`)"
)


def _plain_links(text: str) -> str:
    """Keep both link label and destination, including balanced URL parentheses."""
    out: List[str] = []
    cursor = 0
    scanned_until = 0
    literal_index = 0
    literal_spans = [(match.start(), match.end()) for match in _URL_OR_HTML.finditer(text)]
    for match in re.finditer(r"\[([^\[\]\n]+)\]\(", text):
        if match.start() < scanned_until:
            continue
        while literal_index < len(literal_spans) and literal_spans[literal_index][1] <= match.start():
            literal_index += 1
        if literal_index < len(literal_spans) and literal_spans[literal_index][0] <= match.start():
            continue
        end = match.end()
        depth = 1
        while end < len(text) and text[end] not in "\r\n":
            if text[end] == "(":
                depth += 1
            elif text[end] == ")":
                depth -= 1
                if depth == 0:
                    break
            end += 1
        # Never rescan a suffix already checked for a closing parenthesis. An
        # unmatched opener leaves the rest of its line literal.
        scanned_until = end + 1
        target = text[match.end():end]
        if depth or not target or any(char.isspace() for char in target):
            continue
        out.extend((text[cursor:match.start()], match.group(1), " — ", target))
        cursor = end + 1
    out.append(text[cursor:])
    return "".join(out)


def normalize_plain_text(text: str) -> str:
    """Remove common paired Markdown syntax without interpreting model output.

    This deliberately is not a Markdown parser. Unpaired delimiters, arithmetic,
    intraword underscores, URLs, and raw HTML are ordinary plain text.
    """
    text = _plain_links(text)
    # Protect literal spans while removing surrounding formatting. Pick a marker
    # absent from the input so user/model text cannot collide with placeholders.
    marker = "\x00"
    while marker in text:
        marker += "\x00"
    literals: List[str] = []

    def protect(match: re.Match[str]) -> str:
        literal = match.group(0)
        # A paired wrapper belongs to formatting, not to the enclosed URL.
        if "://" in literal:
            for delimiter in ("**", "__", "*", "_", "`"):
                start = match.start() - len(delimiter)
                if (
                    start >= 0
                    and text[start:match.start()] == delimiter
                    and literal.endswith(delimiter)
                    and delimiter not in literal[:-len(delimiter)]
                ):
                    literal = literal[:-len(delimiter)]
                    break
        literals.append(literal)
        suffix = match.group(0)[len(literal):]
        return f"{marker}{len(literals) - 1}{marker}" + suffix

    text = _URL_OR_HTML.sub(protect, text)
    while True:
        cleaned = _HEADING.sub(r"\1\2", text)
        cleaned = _EMPHASIS.sub(lambda match: next(group for group in match.groups() if group is not None), cleaned)
        if cleaned == text:
            break
        text = cleaned
    return re.sub(
        re.escape(marker) + r"(\d+)" + re.escape(marker),
        lambda match: literals[int(match.group(1))],
        text,
    )


def normalize_payload_text(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize display fields before policies can truncate paired delimiters."""
    for key in ("reply", "follow_up_question"):
        if isinstance(data.get(key), str):
            data[key] = normalize_plain_text(data[key])
    return data


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
    t = normalize_plain_text(text or "").strip()
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

    if isinstance(fu, str):
        fu = normalize_plain_text(fu)
        data["follow_up_question"] = fu
    if isinstance(data.get("reply"), str):
        data["reply"] = normalize_plain_text(data["reply"])

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
