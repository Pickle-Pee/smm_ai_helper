from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from app.services.image_orchestrator import ImageOrchestrator


@dataclass(frozen=True)
class ChatImageResult:
    image: Dict[str, Any]
    reply: str
    follow_up_question: str
    actions: List[Dict[str, str]]


class ChatImageService:
    """Handles image intent detection and chat image generation."""

    IMAGE_KEYWORDS = (
        "сгенерируй картин",
        "сделай картин",
        "картинк",
        "баннер",
        "креатив",
        "обложк",
        "визуал",
        "изображен",
    )

    def __init__(self, image_orchestrator: ImageOrchestrator | None = None) -> None:
        self.image_orchestrator = image_orchestrator or ImageOrchestrator()

    @classmethod
    def wants_image(cls, text: str) -> bool:
        normalized = (text or "").lower()
        return any(keyword in normalized for keyword in cls.IMAGE_KEYWORDS)

    @staticmethod
    def resolve_platform(text: str) -> str:
        normalized = (text or "").lower()
        return "vk" if ("вк" in normalized or "vk" in normalized) else "auto"

    @staticmethod
    def resolve_use_case(text: str) -> str:
        normalized = (text or "").lower()
        return "ad_post" if ("реклам" in normalized or "промо" in normalized) else "post"

    @staticmethod
    def build_brand(facts: Dict[str, Any]) -> Dict[str, Any]:
        facts = facts or {}
        return {
            "brand_name": facts.get("brand_name"),
            "product_description": facts.get("product_description"),
            "audience": facts.get("audience"),
            "tone": facts.get("tone"),
            "goals": facts.get("goals"),
            "channels": facts.get("channels"),
        }

    async def generate_if_requested(
        self,
        text: str,
        user_id: str,
        request_id: str,
        facts: Dict[str, Any],
    ) -> ChatImageResult | None:
        if not self.wants_image(text):
            return None

        result = await self.image_orchestrator.generate(
            platform=self.resolve_platform(text),
            use_case=self.resolve_use_case(text),
            message=text,
            brand=self.build_brand(facts),
            overlay=None,
            variants=1,
            user_id=user_id,
            request_id=request_id,
        )

        return ChatImageResult(
            image={
                "status": "done",
                "mode": result["mode"],
                "preset_id": result["preset_id"],
                "size": result["size"],
                "images": [
                    {"url": f"/images/{image_id}.png"}
                    for image_id in result["image_ids"]
                ],
            },
            reply=(
                "Сгенерировал креатив ✅\n\n"
                "Хочешь ещё 2 варианта? Могу сделать: минимализм / яркий-игровой / премиум."
            ),
            follow_up_question="Какой стиль выбрать: минимализм / яркий / премиум?",
            actions=[
                {"type": "suggestion", "text": "Сделать ещё 2 варианта (разные стили)"},
                {"type": "suggestion", "text": "Добавить текст на баннер (заголовок + CTA)"},
            ],
        )
