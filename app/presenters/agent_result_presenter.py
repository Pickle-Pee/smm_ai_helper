from __future__ import annotations

import json
from typing import Any, Dict, List


def format_agent_result(agent_type: str, result: Dict[str, Any]) -> str:
    """Format raw agent output into user-facing markdown."""
    if isinstance(result.get("user_answer"), str) and result["user_answer"].strip():
        return result["user_answer"].strip()

    if agent_type == "strategy":
        return _format_strategy(result)
    if agent_type == "content":
        return _format_content(result)
    if agent_type == "analytics":
        return _format_analytics(result)
    if agent_type == "promo":
        return _format_promo(result)
    if agent_type == "trends":
        return _format_trends(result)

    return _to_json(result)


def _format_strategy(result: Dict[str, Any]) -> str:
    full = result.get("full_strategy")
    if isinstance(full, str) and full.strip():
        return full.strip()

    structured = result.get("structured") or {}
    summary_text = (result.get("summary_text") or "").strip()
    lines: List[str] = []

    if summary_text:
        lines += ["### Кратко", summary_text, ""]

    positioning = structured.get("positioning") or {}
    if positioning:
        core = positioning.get("core_message")
        utp = positioning.get("utp") or []
        if core:
            lines += ["### Позиционирование", f"**Сообщение:** {core}", ""]
        if utp:
            lines.append("### УТП")
            lines += [f"- {x}" for x in utp[:8]]
            lines.append("")

    first7 = structured.get("first_7_days_plan") or []
    if first7:
        lines.append("### План на первые 7 дней")
        for item in first7[:7]:
            day = item.get("day")
            channel = item.get("channel") or ""
            fmt = item.get("format") or ""
            topic = item.get("topic") or ""
            cta = item.get("cta") or ""
            lines.append(
                f"- День {day}: **{topic}** ({channel}/{fmt})"
                + (f" — CTA: {cta}" if cta else "")
            )

    text = "\n".join(lines).strip()
    return text or _to_json(result)


def _format_content(result: Dict[str, Any]) -> str:
    plan_md = (result.get("raw_plan_markdown") or "").strip()
    posts = result.get("posts") or []
    parts: List[str] = []

    if plan_md:
        parts += ["### Контент-план", plan_md, ""]

    if posts:
        parts.append("### Примеры постов")
        for index, post_item in enumerate(posts[:3], start=1):
            post_obj = post_item.get("post") or {}
            title = post_obj.get("title") or f"Пост #{index}"
            full_text = (post_obj.get("full_text") or "").strip()
            parts.append(f"**{title}**")
            if full_text:
                parts.append(full_text)
            parts.append("")

    text = "\n".join(parts).strip()
    return text or _to_json(result)


def _format_analytics(result: Dict[str, Any]) -> str:
    next_steps = result.get("next_steps") or []
    if isinstance(next_steps, list) and next_steps:
        lines: List[str] = ["### План действий (следующие шаги)"]
        for step in next_steps[:10]:
            if isinstance(step, dict):
                title = (step.get("step") or "").strip()
                impact = (step.get("impact") or "").strip()
                effort = (step.get("effort") or "").strip()
                how = (step.get("how_to_do") or "").strip()
                meta = []
                if impact and impact != "—":
                    meta.append(impact)
                if effort and effort != "—":
                    meta.append(f"усилие: {effort}")
                lines.append(f"- {title}" + (f" ({', '.join(meta)})" if meta else ""))
                if how and how != "—":
                    lines.append(f"  - как сделать: {how}")
            else:
                lines.append(f"- {step}")
        return "\n".join(lines).strip()

    return _to_json(result)


def _format_promo(result: Dict[str, Any]) -> str:
    overall = result.get("overall_approach") or []
    hypotheses = result.get("hypotheses") or []
    lines: List[str] = []

    if overall:
        lines.append("### Подход к рекламе")
        lines.extend([f"- {line}" for line in overall[:8]])
        lines.append("")

    if hypotheses:
        lines.append("### Гипотезы (старт)")
        for hypothesis in hypotheses[:5]:
            name = hypothesis.get("name") or "Гипотеза"
            fmt = hypothesis.get("format") or ""
            segment = hypothesis.get("segment") or ""
            offer = hypothesis.get("offer") or ""
            angle = hypothesis.get("angle") or ""
            lines.append(f"- **{name}**" + (f" ({fmt})" if fmt else ""))
            if segment:
                lines.append(f"  - Сегмент: {segment}")
            if offer:
                lines.append(f"  - Оффер: {offer}")
            if angle:
                lines.append(f"  - Угол: {angle}")

    return "\n".join(lines).strip() or _to_json(result)


def _format_trends(result: Dict[str, Any]) -> str:
    experiments = result.get("experiment_roadmap") or []
    if experiments:
        lines = ["### Эксперименты, которые можно запустить"]
        for experiment in experiments[:6]:
            name = experiment.get("experiment_name") or "Эксперимент"
            hypothesis = experiment.get("hypothesis") or ""
            channel = experiment.get("channel") or ""
            fmt = experiment.get("format") or ""
            lines.append(
                f"- **{name}**" + (f" ({channel}/{fmt})" if channel or fmt else "")
            )
            if hypothesis:
                lines.append(f"  - Гипотеза: {hypothesis}")
        return "\n".join(lines).strip()

    return _to_json(result)


def _to_json(result: Dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)
