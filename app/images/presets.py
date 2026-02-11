# app/images/presets.py
from __future__ import annotations

from typing import Dict, Tuple

PRESETS: Dict[str, Tuple[int, int]] = {
    "ig_post_square": (1080, 1080),
    "ig_story": (1080, 1920),
    "tg_banner": (1280, 720),
    "vk_post": (1080, 1080),
    "web_hero": (1920, 1080),
    "web_block": (1200, 628),
}

# Поддерживаемые размеры для gpt-image-*:
GPT_IMAGE_SIZES = {
    "square": "1024x1024",
    "landscape": "1536x1024",
    "portrait": "1024x1536",
}

def _pick_gpt_generation_size(w: int, h: int) -> str:
    # грубая классификация по соотношению сторон
    r = w / max(h, 1)
    if r > 1.15:
        return GPT_IMAGE_SIZES["landscape"]
    if r < 0.87:
        return GPT_IMAGE_SIZES["portrait"]
    return GPT_IMAGE_SIZES["square"]

def resolve_preset(platform: str, use_case: str) -> tuple[str, str, tuple[int, int]]:
    """
    Возвращает:
    - preset_id
    - generation_size (строка для API, напр. 1024x1024)
    - target_size (w,h) — финальный размер для сохранения/отдачи
    """
    platform = (platform or "auto").lower()
    use_case = (use_case or "auto").lower()

    if use_case == "story":
        preset_id = "ig_story"
    elif use_case == "banner":
        preset_id = "tg_banner"
    elif use_case == "hero":
        preset_id = "web_hero"
    elif use_case == "block":
        preset_id = "web_block"
    elif use_case == "post":
        preset_id = "vk_post" if platform == "vk" else "ig_post_square"
    else:
        if platform == "telegram":
            preset_id = "tg_banner"
        elif platform == "web":
            preset_id = "web_block"
        elif platform == "vk":
            preset_id = "vk_post"
        else:
            preset_id = "ig_post_square"

    target_w, target_h = PRESETS[preset_id]
    generation_size = _pick_gpt_generation_size(target_w, target_h)

    return preset_id, generation_size, (target_w, target_h)
