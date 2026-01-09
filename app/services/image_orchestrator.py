from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any, Dict, List

from app.agents.image_brief_agent import ImageBriefAgent
from app.config import settings
from app.images.presets import resolve_preset
from app.images.template_renderer import TemplateRenderer
from app.llm.openai_images import generate_image


logger = logging.getLogger(__name__)


class ImageOrchestrator:
    def __init__(self) -> None:
        self.brief_agent = ImageBriefAgent()
        self.renderer = TemplateRenderer()
        self.cache: Dict[str, bytes] = {}
        self.image_index: Dict[str, Path] = {}

    def _cache_key(self, prompt: str, size: str, style: str) -> str:
        digest = hashlib.sha256(f"{prompt}|{size}|{style}".encode("utf-8")).hexdigest()
        return digest

    async def _get_background(self, prompt: str, size: str, style: str) -> bytes:
        key = self._cache_key(prompt, size, style)
        if key in self.cache:
            return self.cache[key]
        image_bytes = await generate_image(
            prompt=prompt,
            size=size,
            model=settings.DEFAULT_IMAGE_MODEL,
            quality="standard",
        )
        self.cache[key] = image_bytes
        return image_bytes

    def _save_image(self, image_bytes: bytes, user_id: str) -> str:
        image_id = uuid.uuid4().hex
        base_path = Path(settings.IMAGE_STORAGE_PATH) / user_id
        base_path.mkdir(parents=True, exist_ok=True)
        image_path = base_path / f"{image_id}.png"
        image_path.write_bytes(image_bytes)
        self.image_index[image_id] = image_path
        return image_id

    def resolve_image_path(self, image_id: str) -> Path | None:
        if image_id in self.image_index:
            return self.image_index[image_id]
        base_path = Path(settings.IMAGE_STORAGE_PATH)
        for path in base_path.rglob(f"{image_id}.png"):
            self.image_index[image_id] = path
            return path
        return None

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
        preset_id, size = resolve_preset(platform, use_case)
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
        max_variants = max(1, min(variants, 3))

        for _ in range(max_variants):
            if mode == "simple":
                image_bytes = await self._get_background(prompt, size, style_hint)
            elif mode == "template":
                bg_bytes = await self._get_background(prompt, size, style_hint)
                image_bytes = self.renderer.render(bg_bytes, overlay_data, layout, palette)
            else:
                hybrid_prompt = f"{prompt}\nText overlay: {overlay_data}"
                attempts = 0
                while attempts < settings.IMAGE_MAX_ITERS:
                    image_bytes = await self._get_background(hybrid_prompt, size, style_hint)
                    if confidence != "low":
                        break
                    attempts += 1
                if confidence == "low":
                    bg_bytes = await self._get_background(prompt, size, style_hint)
                    image_bytes = self.renderer.render(bg_bytes, overlay_data, layout, palette)

            image_id = self._save_image(image_bytes, user_id)
            image_ids.append(image_id)

        logger.info(
            "image_generated",
            extra={
                "request_id": request_id or "-",
                "user_id": user_id,
                "image_mode": mode,
            },
        )

        return {
            "mode": mode,
            "preset_id": preset_id,
            "size": size,
            "image_ids": image_ids,
        }
