from __future__ import annotations

from typing import Any, Dict, List


MAX_REPLY_CHARS = 1600
MIN_ACTIONS = 2
MAX_ACTIONS = 4
MAX_BULLETS = 10


def _trim_reply(reply: str) -> str:
    if len(reply) <= MAX_REPLY_CHARS:
        return reply
    return reply[: MAX_REPLY_CHARS - 3].rstrip() + "..."


def _trim_bullets(reply: str) -> str:
    lines = reply.splitlines()
    bullet_lines = [i for i, line in enumerate(lines) if line.strip().startswith(("-", "•"))]
    if len(bullet_lines) <= MAX_BULLETS:
        return reply
    max_index = bullet_lines[MAX_BULLETS - 1]
    trimmed = lines[: max_index + 1]
    return "\n".join(trimmed).strip()


def _ensure_single_question(question: str | None) -> str | None:
    if not question:
        return None
    cleaned = question.strip().split("?")[0].strip()
    return f"{cleaned}?" if cleaned else None


def enforce_policy(response: Dict[str, Any]) -> Dict[str, Any]:
    reply = response.get("reply") or ""
    reply = _trim_bullets(reply)
    reply = _trim_reply(reply)

    actions: List[Dict[str, str]] = response.get("actions") or []
    actions = actions[:MAX_ACTIONS]
    if len(actions) < MIN_ACTIONS:
        actions.append({"type": "suggestion", "text": "Сделать подробнее"})
    actions = actions[:MAX_ACTIONS]

    follow_up = _ensure_single_question(response.get("follow_up_question"))

    response["reply"] = reply
    response["actions"] = actions
    response["follow_up_question"] = follow_up
    return response
