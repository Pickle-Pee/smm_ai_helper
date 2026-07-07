import asyncio

import app.services.task_router as task_router_module
from app.services.task_router import TaskRouter


def test_fallback_decision_uses_hard_defaults_for_strategy():
    decision = TaskRouter().fallback_decision("strategy")

    assert decision == {
        "complexity": "hard",
        "model": "gpt-5",
        "max_output_tokens": 1200,
        "needs_clarification": False,
        "next_questions": [],
        "needs_qc": True,
    }


def test_fallback_decision_uses_light_defaults_for_content():
    decision = TaskRouter().fallback_decision("content")

    assert decision == {
        "complexity": "light",
        "model": "gpt-5-mini",
        "max_output_tokens": 900,
        "needs_clarification": False,
        "next_questions": [],
        "needs_qc": False,
    }


def test_normalize_decision_falls_back_to_agent_complexity():
    decision = TaskRouter()._normalize_decision(
        agent_type="analytics",
        decision={"complexity": "unknown"},
    )

    assert decision["complexity"] == "hard"
    assert decision["model"] == "gpt-5"
    assert decision["max_output_tokens"] == 1600
    assert decision["needs_clarification"] is False
    assert decision["next_questions"] == []
    assert decision["needs_qc"] is True


def test_normalize_decision_clamps_token_limits():
    router = TaskRouter()

    too_low = router._normalize_decision(
        agent_type="content",
        decision={"complexity": "light", "max_output_tokens": 100},
    )
    too_high = router._normalize_decision(
        agent_type="content",
        decision={"complexity": "light", "max_output_tokens": 9999},
    )

    assert too_low["max_output_tokens"] == 600
    assert too_high["max_output_tokens"] == 2400


def test_route_uses_openai_decision(monkeypatch):
    async def fake_openai_chat(**_kwargs):
        return (
            '{"complexity":"hard","max_output_tokens":2000,'
            '"needs_clarification":true,'
            '"next_questions":[{"key":"audience","question":"Кто аудитория?"}],'
            '"needs_qc":true}',
            {"total_tokens": 123},
        )

    monkeypatch.setattr(task_router_module, "openai_chat", fake_openai_chat)

    decision, usage = asyncio.run(
        TaskRouter().route(
            agent_type="strategy",
            task_description="Сделай стратегию",
            answers={},
        )
    )

    assert usage == {"total_tokens": 123}
    assert decision["complexity"] == "hard"
    assert decision["model"] == "gpt-5"
    assert decision["max_output_tokens"] == 2000
    assert decision["needs_clarification"] is True
    assert decision["next_questions"] == [
        {"key": "audience", "question": "Кто аудитория?"}
    ]
    assert decision["needs_qc"] is True


def test_route_falls_back_when_openai_call_fails(monkeypatch):
    async def failing_openai_chat(**_kwargs):
        raise RuntimeError("LLM unavailable")

    monkeypatch.setattr(task_router_module, "openai_chat", failing_openai_chat)

    decision, usage = asyncio.run(
        TaskRouter().route(
            agent_type="content",
            task_description="Сделай пост",
            answers={},
        )
    )

    assert usage == {}
    assert decision == TaskRouter().fallback_decision("content")
