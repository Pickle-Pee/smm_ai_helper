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


def resolve_preset(platform: str, use_case: str) -> tuple[str, str]:
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
        if platform == "vk":
            preset_id = "vk_post"
        else:
            preset_id = "ig_post_square"
    else:
        if platform == "telegram":
            preset_id = "tg_banner"
        elif platform == "web":
            preset_id = "web_block"
        elif platform == "vk":
            preset_id = "vk_post"
        else:
            preset_id = "ig_post_square"

    width, height = PRESETS[preset_id]
    return preset_id, f"{width}x{height}"
