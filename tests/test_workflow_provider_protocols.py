"""Use production HTTP/model/image adapters with a closed fake provider transport."""
import asyncio
import base64
import io
import json

import httpx
from PIL import Image

from app.config import settings
from app.llm.openai_text import chat
from app.services.image_orchestrator import ImageOrchestrator
from app.services.url_analyzer import UrlAnalyzer
from app.workflows.executors import MarketingExecutors
from tests.test_marketing_executors import item
from tests.workflow_fakes import FakeModel


class HtmlStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield ("<html><title>Курс фотографии</title><h1>Консультация по выбору курса</h1>"
               "<main>Познакомьтесь с программой обучения фотографии. Оставьте заявку на консультацию.</main></html>").encode()


def test_real_provider_adapters_generate_three_artifacts_and_a_banner(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "IMAGE_STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://provider.test/v1")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "offline-test-key")
    model = FakeModel()
    seen = []
    buffer = io.BytesIO()
    Image.new("RGB", (1536, 1024), "#234567").save(buffer, format="PNG")
    async def respond(request):
        seen.append((request.url.host, request.url.path))
        if request.url.host == "example.com":
            assert "authorization" not in request.headers
            return httpx.Response(200, headers={"Content-Type": "text/html"}, stream=HtmlStream())
        assert request.url.host == "provider.test" and request.headers["authorization"] == "Bearer offline-test-key"
        payload = json.loads(request.content)
        if request.url.path == "/v1/images/generations":
            return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(buffer.getvalue()).decode()}]})
        assert request.url.path == "/v1/responses"
        fmt = payload.get("text", {}).get("format", {})
        if fmt.get("name", "").startswith("marketing_"):
            assert fmt["strict"] is True
            def check_schema(schema):
                if schema.get("type") == "object":
                    assert schema["additionalProperties"] is False
                    assert set(schema["properties"]) == set(schema["required"])
                for value in schema.values():
                    if isinstance(value, dict): check_schema(value)
                    elif isinstance(value, list):
                        for child in value:
                            if isinstance(child, dict): check_schema(child)
            check_schema(fmt["schema"])
            result, _ = await model(messages=payload["input"], response_format=fmt)
        else:
            result = json.dumps({"mode": "template", "layout": "bottom", "background_prompt": "NO TEXT, dark studio with camera",
                                 "overlay": {}, "palette": ["#FFFFFF"], "confidence": "medium"})
        return httpx.Response(200, json={"status": "completed", "output": [{"type": "message", "role": "assistant",
                             "content": [{"type": "output_text", "text": result}]}], "usage": {"total_tokens": 0}})
    original = httpx.AsyncClient
    def client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(respond)
        return original(**kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", client)
    async def run():
        executor = MarketingExecutors(model_call=chat, analyzer=UrlAnalyzer(), images=ImageOrchestrator())
        analysis = await executor.execute(item())
        creative = await executor.execute(item("creative", {"analysis": analysis}))
        mentor = await executor.execute(item("mentor", {"analysis": analysis, "creative": creative}))
        assert analysis["evidence"][0]["provenance"] == "https://example.com"
        assert mentor["lineage"].keys() == {"analysis", "creative"}
        path = ImageOrchestrator().resolve_image_path(creative["images"][0]["image_id"], user_id="123")
        assert Image.open(path).size == (1280, 720)
        assert seen.count(("provider.test", "/v1/responses")) == 4  # 3 workflow calls + existing image brief.
        assert seen.count(("provider.test", "/v1/images/generations")) == 1
    asyncio.run(run())
