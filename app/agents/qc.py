from __future__ import annotations

from typing import Any, Dict, List


def qc_block(brief: Dict[str, Any]) -> str:
    issues = brief.get("qc_issues")
    if not issues:
        return ""
    if not isinstance(issues, list):
        return ""
    issues = [str(x).strip() for x in issues if str(x).strip()]
    if not issues:
        return ""
    lines = "\n".join([f"- {x}" for x in issues[:8]])
    return (
        "\n\n⚠️ ВАЖНО: Это повторная попытка после QC.\n"
        "Исправь ответ, учитывая замечания (обязательно):\n"
        f"{lines}\n"
        "Не спорь с замечаниями — просто исправь.\n"
    )
