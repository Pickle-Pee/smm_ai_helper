from __future__ import annotations

import re
from typing import Any, Dict, Optional

KV_RE = re.compile(r"^\s*([a-zA-Zа-яА-Я0-9_ \-\/]+)\s*:\s*(.+?)\s*$")
NUM_RE = re.compile(r"(\d[\d\s.,]*)")

def _to_number(s: str) -> Optional[float]:
    if not s:
        return None
    m = NUM_RE.search(s.replace("\u00a0", " "))
    if not m:
        return None
    raw = m.group(1).strip().replace(" ", "").replace(",", ".")
    try:
        return float(raw)
    except Exception:
        return None

def parse_instagram_insights(text: str) -> Optional[Dict[str, Any]]:
    """
    Понимает шаблон IG_INSIGHTS + обычные строки "ключ: значение".
    Возвращает dict или None, если это не похоже на инсайты.
    """
    if not text:
        return None

    low = text.lower()
    is_ig = ("ig_insights" in low) or ("инсайт" in low and "инст" in low) or ("instagram" in low and "insight" in low)
    if not is_ig:
        return None

    data: Dict[str, Any] = {
        "handle": None,
        "goal": None,
        "niche": None,
        "geo": None,
        "language": None,
        "followers": None,
        "avg_reach_post": None,
        "avg_reach_reels": None,
        "avg_saves_post": None,
        "avg_comments_post": None,
        "audience_gender": None,
        "audience_age_top": None,
        "audience_geo_top": None,
        "top_content": [],
        "funnel_link": None,
        "avg_check": None,
        "raw": text[:6000],
    }

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # handle через @
    for ln in lines:
        if "@" in ln:
            m = re.search(r"@([a-zA-Z0-9_\.]{3,30})", ln)
            if m:
                data["handle"] = "@" + m.group(1)
                break

    # KV-парсинг
    for ln in lines:
        m = KV_RE.match(ln)
        if not m:
            continue
        key = m.group(1).strip().lower()
        val = m.group(2).strip()

        # нормализация ключей (рус/англ)
        if key in {"цель", "goal"}:
            data["goal"] = val
        elif key in {"ниша/продукт", "ниша", "продукт", "niche", "product"}:
            data["niche"] = val
        elif key in {"гео", "geo"}:
            data["geo"] = val
        elif key in {"язык", "language"}:
            data["language"] = val
        elif key in {"подписчики", "followers"}:
            data["followers"] = _to_number(val)
        elif key in {"ср.охват поста", "средний охват поста", "avg reach post", "avg_reach_post"}:
            data["avg_reach_post"] = _to_number(val)
        elif key in {"ср.охват рилс", "средний охват рилс", "avg reach reels", "avg_reach_reels"}:
            data["avg_reach_reels"] = _to_number(val)
        elif key in {"ср.сохранения поста", "средние сохранения поста", "avg saves post", "avg_saves_post"}:
            data["avg_saves_post"] = _to_number(val)
        elif key in {"ср.комменты поста", "средние комментарии поста", "avg comments post", "avg_comments_post"}:
            data["avg_comments_post"] = _to_number(val)
        elif key in {"аудитория", "пол", "gender"}:
            data["audience_gender"] = val
        elif key in {"возраст топ-3", "возраст", "age"}:
            data["audience_age_top"] = val
        elif key in {"топ-гео", "гео аудитории", "audience geo", "geo_top"}:
            data["audience_geo_top"] = val
        elif key in {"ссылки/воронка", "воронка", "ссылка", "funnel", "link"}:
            data["funnel_link"] = val
        elif key in {"средний чек", "avg_check", "avg check"}:
            data["avg_check"] = _to_number(val)

    # top content: строки вида "1) тема — охват — сохранения — комментарии"
    tc = []
    for ln in lines:
        if re.match(r"^\d+\)", ln) or re.match(r"^\d+\.", ln):
            tc.append(ln[:400])
    if tc:
        data["top_content"] = tc[:10]

    return data
