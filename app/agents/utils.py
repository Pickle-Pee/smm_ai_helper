# app/agents/utils.py
from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional
import json
import re


@dataclass
class BriefContext:
    """Нормализованный бриф, с которым работают все агенты."""

    task_description: str = ""
    brand_name: str = "бренд"
    product_description: str = ""
    audience: str = ""
    goals: str = ""
    channels: List[str] = field(default_factory=list)
    tone: str = "дружелюбный, экспертный, без канцелярита"
    geo: Optional[str] = None
    price_segment: Optional[str] = None
    niche: Optional[str] = None
    budget: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        # убираем None, чтобы не засорять промпты
        return {k: v for k, v in data.items() if v not in (None, [], "")}


def normalize_channels(channels: Any) -> List[str]:
    if channels is None:
        return []
    if isinstance(channels, list):
        return [str(c).strip() for c in channels if str(c).strip()]
    if isinstance(channels, str):
        parts = [p.strip() for p in channels.split(",")]
        return [p for p in parts if p]
    return [str(channels)]


def normalize_brief(raw: Dict[str, Any]) -> BriefContext:
    """Приводим все ключи к единому виду, добавляем разумные дефолты."""
    return BriefContext(
        task_description=str(raw.get("task_description", "")),
        brand_name=str(raw.get("brand_name") or raw.get("project_name") or "бренд"),
        product_description=str(raw.get("product_description", "")),
        audience=str(raw.get("audience", "")),
        goals=str(raw.get("goals") or raw.get("goal") or ""),
        channels=normalize_channels(raw.get("channels")),
        tone=str(raw.get("tone") or "дружелюбный, экспертный, без канцелярита"),
        geo=raw.get("geo"),
        price_segment=raw.get("price_segment"),
        niche=raw.get("niche"),
        budget=raw.get("budget"),
        extra=raw.get("extra") or {},
    )


def safe_json_parse(raw: str) -> Dict[str, Any]:
    """
    Аккуратно вытаскиваем JSON из ответа модели:
    - убираем ```json fences
    - нормализуем “умные” кавычки
    - пытаемся распарсить как есть
    - fallback: берём подстроку между первой '{' и последней '}'
    """
    raw_str = raw.strip()
    raw_str = re.sub(r"^```(?:json)?", "", raw_str, flags=re.IGNORECASE).strip()
    raw_str = re.sub(r"```$", "", raw_str).strip()
    raw_str = (
        raw_str.replace("“", '"')
        .replace("”", '"')
        .replace("’", "'")
        .replace("‘", "'")
    )
    try:
        return json.loads(raw_str)
    except json.JSONDecodeError:
        first = raw_str.find("{")
        last = raw_str.rfind("}")
        if first != -1 and last != -1 and last > first:
            return json.loads(raw_str[first : last + 1])
        raise
