# app/services/image_orchestrator.py
from __future__ import annotations

import hashlib
import io
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

from PIL import Image

from app.agents.image_brief_agent import ImageBriefAgent
from app.config import settings
from app.images.presets import resolve_preset
from app.images.template_renderer import TemplateRenderer
from app.llm.openai_images import generate_image

logger = logging.getLogger(__name__)


def _pick_generation_size(target_w: int, target_h: int) -> str:
    if target_w == target_h:
        return "1024x1024"
    if target_w > target_h:
        return "1536x1024"
    return "1024x1536"


def _parse_size(s: str) -> Tuple[int, int]:
    w, h = s.lower().split("x")
    return int(w), int(h)


def _resize_to_target(image_bytes: bytes, target_size: str) -> bytes:
    target_w, target_h = _parse_size(target_size)
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    resized = img.resize((target_w, target_h), Image.LANCZOS)

    out = io.BytesIO()
    resized.save(out, format="PNG")
    return out.getvalue()


class ImageOrchestrator:
    def __init__(self) -> None:
        self.brief_agent = ImageBriefAgent()
        self.renderer = TemplateRenderer()
        self.cache: Dict[str, bytes] = {}
        self.image_index: Dict[str, Path] = {}

    def _cache_key(self, prompt: str, size: str, style: str, model: str, quality: str) -> str:
        digest = hashlib.sha256(f"{model}|{quality}|{prompt}|{size}|{style}".encode("utf-8")).hexdigest()
        return digest

    def _resize_cover(self, image_bytes: bytes, target_size: Tuple[int, int]) -> bytes:
        tw, th = target_size
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size

        # cover scale
        scale = max(tw / w, th / h)
        nw, nh = int(w * scale), int(h * scale)
        img = img.resize((nw, nh), Image.LANCZOS)

        # center crop
        left = max((nw - tw) // 2, 0)
        top = max((nh - th) // 2, 0)
        img = img.crop((left, top, left + tw, top + th))

        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    def _save_image(self, image_bytes: bytes, user_id: str) -> str:
        """
        Сохраняет png на диск и возвращает image_id.
        """
        image_id = uuid.uuid4().hex
        base_path = Path(settings.IMAGE_STORAGE_PATH) / (user_id or "anonymous")
        base_path.mkdir(parents=True, exist_ok=True)

        image_path = base_path / f"{image_id}.png"
        image_path.write_bytes(image_bytes)

        # индекс для быстрого доступа
        self.image_index[image_id] = image_path
        return image_id

    def resolve_image_path(self, image_id: str) -> Optional[Path]:
        """
        Возвращает путь к image_id.png, если файл существует.
        """
        p = self.image_index.get(image_id)
        if p and p.exists():
            return p

        base_path = Path(settings.IMAGE_STORAGE_PATH)
        # фолбэк: ищем по диску
        for path in base_path.rglob(f"{image_id}.png"):
            self.image_index[image_id] = path
            return path

        return None

    async def _get_background(self, prompt: str, generation_size: str, style: str, *, user_id: str) -> bytes:
        model = settings.DEFAULT_IMAGE_MODEL
        quality = getattr(settings, "DEFAULT_IMAGE_QUALITY", "auto")

        key = self._cache_key(prompt, generation_size, style, model=model, quality=quality)
        if key in self.cache:
            return self.cache[key]

        image_bytes = await generate_image(
            prompt=prompt,
            size=generation_size,
            model=model,
            quality=quality,
            user=user_id,
        )
        self.cache[key] = image_bytes
        return image_bytes

    async def generate(
        self,
        platform: str,
        use_case: str,
        message: str,
        brand: Dict[str, Any] | None,
        overlay: Dict[str, str] | None,
        variants: int = 1,
        user_id: str = "anonymous",
        request_id: str | None = None,
    ) -> Dict[str, Any]:
        brief = await self.brief_agent.run(
            platform=platform,
            use_case=use_case,
            message=message,
            brand=brand,
            overlay_text=overlay,
        )

        preset_id, generation_size, target_size = resolve_preset(platform, use_case)

        mode = brief.get("mode", "simple")
        background_prompt = brief.get("background_prompt") or message
        negative_prompt = brief.get("negative_prompt") or ""
        overlay_data = brief.get("overlay") or overlay or {}
        layout = brief.get("layout") or "center"
        palette = brief.get("palette") or []
        confidence = brief.get("confidence") or "medium"

        style_hint = ",".join(palette) if palette else "neutral"
        prompt = background_prompt
        if negative_prompt:
            prompt = f"{prompt}\nNegative prompt: {negative_prompt}"

        image_ids: List[str] = []
        max_variants = max(1, min(int(variants or 1), 3))

        for _ in range(max_variants):
            if mode == "simple":
                bg = await self._get_background(prompt, generation_size, style_hint, user_id=user_id)
                image_bytes = self._resize_cover(bg, target_size)

            elif mode == "template":
                bg = await self._get_background(prompt, generation_size, style_hint, user_id=user_id)
                bg = self._resize_cover(bg, target_size)
                image_bytes = self.renderer.render(bg, overlay_data, layout, palette)

            else:
                hybrid_prompt = f"{prompt}\nText overlay: {overlay_data}"
                bg = await self._get_background(hybrid_prompt, generation_size, style_hint, user_id=user_id)
                image_bytes = self._resize_cover(bg, target_size)

                # fallback если уверенность низкая — делаем template-рендер
                if confidence == "low":
                    bg2 = await self._get_background(prompt, generation_size, style_hint, user_id=user_id)
                    bg2 = self._resize_cover(bg2, target_size)
                    image_bytes = self.renderer.render(bg2, overlay_data, layout, palette)

            image_id = self._save_image(image_bytes, user_id)
            image_ids.append(image_id)

        logger.info(
            "image_generated",
            extra={"request_id": request_id or "-", "user_id": user_id, "image_mode": mode},
        )

        return {
            "mode": mode,
            "preset_id": preset_id,
            "size": f"{target_size[0]}x{target_size[1]}",
            "image_ids": image_ids,
        }