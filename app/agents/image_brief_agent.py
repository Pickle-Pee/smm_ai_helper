# app/agents/image_brief_agent.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.agents.utils import safe_json_parse
from app.agents.qc import qc_block


# Популярные форматы (можно расширять)
PRESETS: Dict[str, Dict[str, Any]] = {
    # Instagram
    "instagram_post": {"w": 1080, "h": 1080, "aspect": "1:1"},
    "instagram_story": {"w": 1080, "h": 1920, "aspect": "9:16"},
    # Telegram
    "telegram_banner": {"w": 1280, "h": 720, "aspect": "16:9"},
    "telegram_post": {"w": 1200, "h": 675, "aspect": "16:9"},
    # VK
    "vk_post": {"w": 1080, "h": 1080, "aspect": "1:1"},
    "vk_story": {"w": 1080, "h": 1920, "aspect": "9:16"},
    # Web
    "web_banner": {"w": 1200, "h": 628, "aspect": "1.91:1"},
    "web_hero": {"w": 1440, "h": 900, "aspect": "16:10"},
}


def _choose_preset(platform: str, use_case: str) -> str:
    p = (platform or "").lower()
    u = (use_case or "").lower()

    if "insta" in p:
        if "story" in u or "storis" in u:
            return "instagram_story"
        return "instagram_post"

    if "telegram" in p or p in {"tg", "t.me"}:
        if "banner" in u:
            return "telegram_banner"
        return "telegram_post"

    if "vk" in p or "vkontakte" in p:
        if "story" in u:
            return "vk_story"
        return "vk_post"

    if "web" in p or "site" in p or "landing" in p:
        if "hero" in u:
            return "web_hero"
        return "web_banner"

    # fallback
    return "instagram_post"


class ImageBriefAgent:
    system_prompt = (
        "Ты — арт-директор и продюсер визуальных материалов для SMM.\n"
        "Твоя задача: сделать техзадание для генерации картинки и (если нужно) шаблон для наложения текста.\n"
        "Отвечай строго валидным JSON-объектом без текста до/после.\n\n"
        "ЖЁСТКИЕ ПРАВИЛА:\n"
        "- background_prompt: НИКАКОГО ТЕКСТА в изображении (NO TEXT / no lettering / no words / no typography).\n"
        "- Все слова/тексты должны быть только в overlay.\n"
        "- Если пользователь не просил текст внутри картинки и overlay_text пустой — предпочитай mode=simple.\n"
        "- Если это баннер/обложка/hero или есть overlay_text → mode=template.\n"
        "- mode=hybrid только если пользователь явно хочет текст в картинке, но мы всё равно делаем overlay (текст не рисуем).\n"
        "- Избегай клише: 'modern, sleek' без деталей. Давай конкретные визуальные подсказки.\n"
    )

    async def run(
        self,
        platform: str,
        use_case: str,
        message: str,
        brand: Dict[str, Any] | None,
        overlay_text: Dict[str, str] | None,
        qc_issues: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        brand = brand or {}
        overlay_text = overlay_text or {}

        # превратим qc_issues в brief для qc_block
        qc = qc_block({"qc_issues": qc_issues} if qc_issues else {})

        preset_id = _choose_preset(platform, use_case)
        preset = PRESETS.get(preset_id, PRESETS["instagram_post"])

        # режимы
        wants_text = bool(overlay_text) or any(
            kw in (message or "").lower()
            for kw in ["текст", "надпись", "заголовок", "сделай баннер", "banner", "обложк", "hero"]
        )
        is_banner = any(kw in (use_case or "").lower() for kw in ["banner", "баннер", "обложк", "hero", "cover"])

        # простая логика выбора mode (модель может переопределить, но мы подталкиваем)
        suggested_mode = "simple"
        if is_banner or overlay_text:
            suggested_mode = "template"
        if wants_text and (is_banner or overlay_text):
            suggested_mode = "hybrid"  # текст хотим, но реализуем через overlay

        prompt = f"""
Платформа: {platform}
Use case: {use_case}
Сообщение/смысл: {message}

Бренд (если есть):
{brand}

Текст для наложения (если есть):
{overlay_text}

Preset (уже выбран):
{{
  "preset_id": "{preset_id}",
  "w": {preset["w"]},
  "h": {preset["h"]},
  "aspect": "{preset["aspect"]}"
}}

Предложенный режим: {suggested_mode}

Верни JSON:
{{
  "mode": "simple|template|hybrid",
  "preset_id": "{preset_id}",
  "size": "{preset["w"]}x{preset["h"]}",
  "aspect": "{preset["aspect"]}",
  "background_prompt": "NO TEXT, конкретная сцена/композиция/стиль, negative space под overlay",
  "negative_prompt": "text, words, letters, watermark, logo artifacts, low quality, blurry",
  "overlay": {{
    "headline": "...",
    "subtitle": "...",
    "cta": "..."
  }},
  "palette": ["#RRGGBB", "#RRGGBB", "#RRGGBB"],
  "layout": "left|center|bottom",
  "notes": ["короткие подсказки для верстки/отступов/контраста"],
  "confidence": "low|medium|high"
}}

Правила выбора:
- Если overlay_text пустой и баннер НЕ нужен → mode=simple, overlay может быть пустым (headline/subtitle/cta="").
- Если это баннер/обложка/hero ИЛИ overlay_text задан → mode=template, заполни overlay (можно коротко).
- Если пользователь явно хочет текст в картинке → mode=hybrid, НО background_prompt всё равно БЕЗ ТЕКСТА.

Правила качества:
- background_prompt должен описывать: сюжет, ключевые объекты, стиль (референс/жанр), свет, композицию,
  и обязательно "NO TEXT" + "negative space for overlay".
- palette: 3–5 цветов, которые будут сочетаться и давать контраст для текста.
- layout: выбери, где будет блок текста (left/center/bottom), учитывая negative space.

{qc}
""".strip()

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]

        content, usage = await openai_chat(
            messages=messages,
            model=settings.DEFAULT_TEXT_MODEL_LIGHT,
            response_format={"type": "json_object"},
            task="image_brief",
        )

        data = safe_json_parse(content)

        # Пост-нормализация для безопасности
        data.setdefault("preset_id", preset_id)
        data.setdefault("size", f"{preset['w']}x{preset['h']}")
        data.setdefault("aspect", preset["aspect"])
        data.setdefault("negative_prompt", "text, words, letters, watermark, logo artifacts, low quality, blurry")
        data.setdefault("palette", [])
        data.setdefault("layout", "center")
        data.setdefault("overlay", {"headline": "", "subtitle": "", "cta": ""})
        data.setdefault("notes", [])
        data.setdefault("confidence", "medium")

        # Жёстко гарантируем правило "NO TEXT" в background_prompt
        bp = (data.get("background_prompt") or "").strip()
        if "no text" not in bp.lower():
            data["background_prompt"] = ("NO TEXT. " + bp).strip()

        # Если mode simple — overlay делаем пустым (чтобы не ломать downstream)
        if data.get("mode") == "simple":
            data["overlay"] = {"headline": "", "subtitle": "", "cta": ""}

        return data
