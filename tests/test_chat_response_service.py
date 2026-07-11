import asyncio

import app.services.chat_response_service as chat_response_module
from app.services.chat_response_service import ChatResponseService


class FakeLogger:
    def __init__(self):
        self.exceptions = []

    def exception(self, message):
        self.exceptions.append(message)


def test_normalize_applies_policy_before_payload_normalization(monkeypatch):
    calls = []

    def fake_enforce_policy(payload):
        calls.append(("policy", payload))
        return {**payload, "policy": True}

    def fake_normalize(payload):
        calls.append(("normalize", payload))
        return {"reply": payload["reply"], "normalized": True}

    monkeypatch.setattr(chat_response_module, "enforce_policy", fake_enforce_policy)
    monkeypatch.setattr(chat_response_module, "normalize_assistant_payload", fake_normalize)

    result = ChatResponseService.normalize({"reply": "Blocked"})

    assert result == {"reply": "Blocked", "normalized": True}
    assert calls == [
        ("policy", {"reply": "Blocked"}),
        ("normalize", {"reply": "Blocked", "policy": True}),
    ]


def test_generate_runs_core_policy_qc_policy_and_normalize(monkeypatch):
    calls = []

    async def fake_generate_assistant_reply(**kwargs):
        calls.append(("generate", kwargs))
        return {"reply": "Raw"}

    def fake_enforce_policy(payload):
        calls.append(("policy", payload))
        return {**payload, "policy_passes": payload.get("policy_passes", 0) + 1}

    async def fake_qc_shorten(payload):
        calls.append(("qc", payload))
        return {**payload, "reply": "Short"}

    def fake_normalize(payload):
        calls.append(("normalize", payload))
        return {
            "reply": payload["reply"],
            "follow_up_question": None,
            "actions": [],
        }

    monkeypatch.setattr(
        chat_response_module,
        "generate_assistant_reply",
        fake_generate_assistant_reply,
    )
    monkeypatch.setattr(chat_response_module, "enforce_policy", fake_enforce_policy)
    monkeypatch.setattr(chat_response_module, "qc_shorten", fake_qc_shorten)
    monkeypatch.setattr(chat_response_module, "normalize_assistant_payload", fake_normalize)

    result = asyncio.run(
        ChatResponseService().generate(
            user_message="Сделай пост",
            summary="Summary",
            facts_json={"brand_name": "Brand"},
            last_messages=[{"role": "user", "text": "Сделай пост"}],
            url_summaries=[{"title": "Example"}],
        )
    )

    assert result == {
        "reply": "Short",
        "follow_up_question": None,
        "actions": [],
    }
    assert calls == [
        (
            "generate",
            {
                "user_message": "Сделай пост",
                "summary": "Summary",
                "facts_json": {"brand_name": "Brand"},
                "last_messages": [{"role": "user", "text": "Сделай пост"}],
                "url_summaries": [{"title": "Example"}],
            },
        ),
        ("policy", {"reply": "Raw"}),
        ("qc", {"reply": "Raw", "policy_passes": 1}),
        ("policy", {"reply": "Short", "policy_passes": 1}),
        (
            "normalize",
            {"reply": "Short", "policy_passes": 2},
        ),
    ]


def test_generate_falls_back_to_policy_result_when_qc_fails(monkeypatch):
    logger = FakeLogger()
    policy_calls = []

    async def fake_generate_assistant_reply(**_kwargs):
        return {"reply": "Raw"}

    def fake_enforce_policy(payload):
        policy_calls.append(payload)
        return {**payload, "safe": True}

    async def failing_qc_shorten(_payload):
        raise RuntimeError("QC unavailable")

    def fake_normalize(payload):
        return {
            "reply": payload["reply"],
            "safe": payload["safe"],
        }

    monkeypatch.setattr(
        chat_response_module,
        "generate_assistant_reply",
        fake_generate_assistant_reply,
    )
    monkeypatch.setattr(chat_response_module, "enforce_policy", fake_enforce_policy)
    monkeypatch.setattr(chat_response_module, "qc_shorten", failing_qc_shorten)
    monkeypatch.setattr(chat_response_module, "normalize_assistant_payload", fake_normalize)

    result = asyncio.run(
        ChatResponseService(logger).generate(
            user_message="Сделай пост",
            summary="",
            facts_json={},
            last_messages=[],
        )
    )

    assert result == {"reply": "Raw", "safe": True}
    assert logger.exceptions == ["qc_shorten failed unexpectedly"]
    assert policy_calls == [
        {"reply": "Raw"},
        {"reply": "Raw", "safe": True},
    ]
