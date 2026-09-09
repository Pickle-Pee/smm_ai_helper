import asyncio
import copy
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image, ImageDraw

from app.config import settings
from app.images.template_renderer import TemplateRenderer
from app.services.image_orchestrator import ImageOrchestrator
from app.workflows.executors import InvalidModelOutput, MarketingExecutors
from app.workflows.presentation import delivery_parts, render_artifact
from app.workflows.schemas import CreativeResult, StartRequest
from bot.handlers.workflow import continue_workflow
from tests.workflow_fakes import FakeAnalyzer, FakeImages, FakeModel


def item(step="analysis", artifacts=None):
    return SimpleNamespace(job_id="j" * 32, run_id="a" * 32, step=step,
        snapshot={"telegram_id": 123, "competitor_url": "https://example.com", "product": "Курс фотографии",
                  "audience": "Начинающие", "goal": "Заявки", "brand": {}, "captured_at": "2026-09-08T12:00:00+00:00"},
        artifacts=artifacts or {})


@pytest.mark.parametrize("defect", ["unknown_evidence", "unknown_output", "business_observation", "nul", "bad_lineage"])
def test_untrusted_model_references_never_become_saved_evidence(defect):
    async def run():
        model = FakeModel()
        async def malformed(**kwargs):
            text, usage = await model(**kwargs)
            result = json.loads(text)
            claim = result["claims"][0]
            if defect == "unknown_evidence": claim["evidence_ids"] = ["invented"]
            elif defect == "unknown_output": claim["output_name"] = "invented"
            elif defect == "business_observation":
                claim["kind"] = "OBSERVATION"
                claim["evidence_ids"] = [f"evd_{item().run_id}_business"]
            elif defect == "nul": result["assumptions"] = ["bad\x00text"]
            else: claim["parent_claim_ids"] = ["invented"]
            return json.dumps(result), usage
        executors = MarketingExecutors(model_call=malformed, analyzer=FakeAnalyzer(), images=FakeImages())
        with pytest.raises(InvalidModelOutput): await executors.execute(item())
    asyncio.run(run())


def test_confidence_and_lineage_are_inherited_and_creative_uses_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "IMAGE_STORAGE_PATH", str(tmp_path))
    async def run():
        model, images = FakeModel(), FakeImages()
        executors = MarketingExecutors(model_call=model, analyzer=FakeAnalyzer(), images=images)
        analysis = await executors.execute(item())
        async def overconfident(**kwargs):
            text, usage = await model(**kwargs)
            data = json.loads(text)
            data["claims"][0]["confidence"] = "MEDIUM"
            return json.dumps(data), usage
        executors.model_call = overconfident
        creative = await executors.execute(item("creative", {"analysis": analysis}))
        assert creative["result"]["claims"][0]["confidence"] == "LOW"
        assert creative["result"]["claims"][0]["parent_claim_ids"] == analysis["claim_ids"]
        assert images.calls[0]["brand"]["product_description"] == item().snapshot["product"]
        assert images.calls[0]["render_overlay"] is True
        for end in (14, 61):
            invalid = copy.deepcopy(creative["result"])
            invalid["scenes"][-1]["end_seconds"] = end
            with pytest.raises(ValueError): CreativeResult.model_validate(invalid)
    asyncio.run(run())


def test_continuation_callback_uses_pressing_user(monkeypatch):
    from bot import backend
    call = AsyncMock(return_value={"run_id": "a" * 32, "status": "queued"})
    monkeypatch.setattr(backend, "request", call)
    message = SimpleNamespace(from_user=SimpleNamespace(id=999), chat=SimpleNamespace(type="private"), answer=AsyncMock())
    callback = SimpleNamespace(from_user=SimpleNamespace(id=123), message=message,
                               data="mvp:" + "a" * 32 + ":creative", answer=AsyncMock())
    asyncio.run(continue_workflow(callback))
    assert call.call_args.args == ("POST", "/workflows/" + "a" * 32 + "/continue", 123)


def test_large_artifact_is_delivered_without_truncation():
    async def run():
        artifact = await MarketingExecutors(model_call=FakeModel(), analyzer=FakeAnalyzer()).execute(item())
        artifact["result"]["practical_brief"] = "Тест 🚀\n" * 1500
        parts = delivery_parts(artifact)
        assert "".join(p["text"] for p in parts) == render_artifact(artifact)
        assert all(len(p["text"].encode("utf-16-le")) // 2 <= 3500 for p in parts)
        assert len(parts[-1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"].encode()) <= 64
    asyncio.run(run())


@pytest.mark.parametrize("bad", ["\x00", "\ud800"])
def test_business_input_rejects_non_postgres_text(bad):
    with pytest.raises(ValueError):
        StartRequest(request_key="test", competitor_url="https://example.com", product=bad)


@pytest.mark.parametrize("layout", ["center", "left", "bottom"])
def test_banner_preserves_copy_and_fits_cyrillic_inside_image(monkeypatch, tmp_path, layout):
    monkeypatch.setattr(settings, "IMAGE_STORAGE_PATH", str(tmp_path))
    overlay = {"headline": "Выберите практический курс фотографии и начните уверенно снимать портреты для своих первых клиентов",
               "cta": "Посмотреть подробную программу и выбрать удобное время"}
    calls = []
    original = ImageDraw.ImageDraw.text
    def record(draw, xy, text, **kwargs):
        bbox = draw.textbbox(xy, text, font=kwargs["font"])
        assert min(bbox[:2]) >= 0 and bbox[2] < 1280 and bbox[3] < 720
        calls.append(text)
        return original(draw, xy, text, **kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw, "text", record)
    async def run():
        orchestrator = ImageOrchestrator()
        orchestrator.brief_agent.run = AsyncMock(return_value={"mode": "simple", "overlay": {"headline": "Changed"},
                                                             "layout": layout, "palette": ["invalid-color"]})
        background = io.BytesIO()
        Image.new("RGB", (1200, 675), "#456789").save(background, format="PNG")
        orchestrator._get_background = AsyncMock(return_value=background.getvalue())
        result = await orchestrator.generate("telegram", "banner", "banner", {}, overlay, user_id="123", render_overlay=True)
        path = ImageOrchestrator().resolve_image_path(result["image_ids"][0], user_id="123")
        assert Image.open(path).size == (1280, 720) and result["mode"] == "template"
        assert " ".join(calls[::2]) == " ".join(overlay.values())  # Every word, no clipped/changed copy.
    asyncio.run(run())
