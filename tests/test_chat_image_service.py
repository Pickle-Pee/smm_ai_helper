import asyncio

from app.services.chat_image_service import ChatImageService


class FakeImageOrchestrator:
    def __init__(self):
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "mode": "mock",
            "preset_id": "preset-1",
            "size": "1024x1024",
            "image_ids": ["img-1", "img-2"],
        }


def test_wants_image_detects_image_requests():
    assert ChatImageService.wants_image("Сгенерируй картинку для поста") is True
    assert ChatImageService.wants_image("Сделай баннер для ВК") is True
    assert ChatImageService.wants_image("Напиши пост") is False


def test_resolve_platform_detects_vk():
    assert ChatImageService.resolve_platform("Сделай баннер для ВК") == "vk"
    assert ChatImageService.resolve_platform("Сделай баннер для vk") == "vk"
    assert ChatImageService.resolve_platform("Сделай баннер") == "auto"


def test_resolve_use_case_detects_ad_post():
    assert ChatImageService.resolve_use_case("Сделай рекламный креатив") == "ad_post"
    assert ChatImageService.resolve_use_case("Сделай промо баннер") == "ad_post"
    assert ChatImageService.resolve_use_case("Сделай визуал для поста") == "post"


def test_build_brand_maps_known_fact_fields():
    assert ChatImageService.build_brand(
        {
            "brand_name": "Brand",
            "product_description": "Product",
            "audience": "Audience",
            "tone": "Tone",
            "goals": ["Goal"],
            "channels": ["Telegram"],
            "ignored": "value",
        }
    ) == {
        "brand_name": "Brand",
        "product_description": "Product",
        "audience": "Audience",
        "tone": "Tone",
        "goals": ["Goal"],
        "channels": ["Telegram"],
    }


def test_generate_if_requested_returns_none_when_no_image_intent():
    orchestrator = FakeImageOrchestrator()
    service = ChatImageService(image_orchestrator=orchestrator)

    result = asyncio.run(
        service.generate_if_requested(
            text="Напиши пост",
            user_id="user-1",
            request_id="request-1",
            facts={},
        )
    )

    assert result is None
    assert orchestrator.calls == []


def test_generate_if_requested_calls_orchestrator_and_formats_result():
    orchestrator = FakeImageOrchestrator()
    service = ChatImageService(image_orchestrator=orchestrator)

    result = asyncio.run(
        service.generate_if_requested(
            text="Сделай рекламный баннер для ВК",
            user_id="user-1",
            request_id="request-1",
            facts={"brand_name": "Brand", "audience": "Audience"},
        )
    )

    assert result is not None
    assert result.image == {
        "status": "done",
        "mode": "mock",
        "preset_id": "preset-1",
        "size": "1024x1024",
        "images": [
            {"url": "/images/img-1.png"},
            {"url": "/images/img-2.png"},
        ],
    }
    assert result.reply.startswith("Сгенерировал креатив")
    assert result.follow_up_question == "Какой стиль выбрать: минимализм / яркий / премиум?"
    assert result.actions == [
        {"type": "suggestion", "text": "Сделать ещё 2 варианта (разные стили)"},
        {"type": "suggestion", "text": "Добавить текст на баннер (заголовок + CTA)"},
    ]
    assert orchestrator.calls == [
        {
            "platform": "vk",
            "use_case": "ad_post",
            "message": "Сделай рекламный баннер для ВК",
            "brand": {
                "brand_name": "Brand",
                "product_description": None,
                "audience": "Audience",
                "tone": None,
                "goals": None,
                "channels": None,
            },
            "overlay": None,
            "variants": 1,
            "user_id": "user-1",
            "request_id": "request-1",
        }
    ]
