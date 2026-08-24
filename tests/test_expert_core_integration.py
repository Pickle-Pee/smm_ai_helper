from __future__ import annotations

import asyncio
import logging

import app.agents.base as base_module
from app.agents.base import BaseAgent
from app.agents.content_agent import ContentAgent
from app.services.agent_registry import AgentRegistry
from app.services.expert_instruction_composer import (
    EXPERT_CORE_START_PREFIX,
    RESPONSE_MODE_START,
    SPECIALIZED_MODULE_START,
)


class DummyAgent(BaseAgent):
    system_prompt = "PRIVATE MODULE INSTRUCTIONS"

    async def run(self, brief, **kwargs):
        return {}


class OpenAICallFake:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0), {"input_tokens": 1}


def test_llm_text_composes_once_and_keeps_existing_call_settings(monkeypatch):
    fake = OpenAICallFake(["result"])
    monkeypatch.setattr(base_module, "openai_chat", fake)
    agent = DummyAgent()
    agent.model_override = "model-override"
    agent.max_output_tokens_override = 777

    result = asyncio.run(agent.llm_text("USER MATERIAL"))

    assert result == "result"
    assert len(fake.calls) == 1
    call = fake.calls[0]
    system = call["messages"][0]["content"]
    assert system.count(EXPERT_CORE_START_PREFIX) == 1
    assert system.index(SPECIALIZED_MODULE_START) < system.index(
        DummyAgent.system_prompt
    )
    assert call["messages"][1] == {"role": "user", "content": "USER MATERIAL"}
    assert call["model"] == "model-override"
    assert call["max_output_tokens"] == 777
    assert "response_format" not in call


def test_llm_json_composes_response_mode_once_and_preserves_schema(monkeypatch):
    fake = OpenAICallFake(['{"ok": true}'])
    monkeypatch.setattr(base_module, "openai_chat", fake)

    result = asyncio.run(
        DummyAgent().llm_json(
            "USER MATERIAL",
            '{"ok": "boolean"}',
            model="model-explicit",
        )
    )

    assert result == {"ok": True}
    assert len(fake.calls) == 1
    call = fake.calls[0]
    system = call["messages"][0]["content"]
    assert system.count(EXPERT_CORE_START_PREFIX) == 1
    assert system.count(RESPONSE_MODE_START) == 1
    assert "Отвечай строго валидным JSON-объектом" in system
    assert '{"ok": "boolean"}' in system
    assert call["response_format"] == {"type": "json_object"}
    assert call["model"] == "model-explicit"


def test_diagnostics_include_version_and_agent_only(monkeypatch, caplog):
    fake = OpenAICallFake(["result"])
    monkeypatch.setattr(base_module, "openai_chat", fake)

    with caplog.at_level(logging.INFO, logger="app.agents.base"):
        asyncio.run(DummyAgent().llm_text("PRIVATE USER MATERIAL"))

    record = next(
        item for item in caplog.records if item.message == "Expert Core instructions composed"
    )
    assert record.expert_core_version == "1.0.0"
    assert record.agent_type == "DummyAgent"
    assert "PRIVATE MODULE INSTRUCTIONS" not in record.getMessage()
    assert "PRIVATE USER MATERIAL" not in record.getMessage()


def test_all_registered_agents_use_shared_json_request_boundary(monkeypatch):
    fake = OpenAICallFake(['{"ok": true}'] * 5)
    monkeypatch.setattr(base_module, "openai_chat", fake)

    for agent_type in sorted(AgentRegistry.supported_agent_types()):
        agent_class = AgentRegistry.get_agent_class(agent_type)
        assert agent_class is not None
        assert issubclass(agent_class, BaseAgent)
        assert agent_class.llm_json is BaseAgent.llm_json
        result = asyncio.run(agent_class().llm_json("input", '{"ok": true}'))
        assert result == {"ok": True}

    assert len(fake.calls) == 5
    for call in fake.calls:
        assert call["messages"][0]["content"].count(EXPERT_CORE_START_PREFIX) == 1


def test_content_agent_multi_request_run_composes_once_per_call(monkeypatch):
    plan = (
        '[{"date":"2026-08-24","format":"пост","topic":"one"},'
        '{"date":"2026-08-25","format":"пост","topic":"two"}]'
    )
    fake = OpenAICallFake([plan, "{}", "{}"])
    monkeypatch.setattr(base_module, "openai_chat", fake)

    result = asyncio.run(
        ContentAgent().run(
            {
                "task_description": "Составь контент-план",
                "channels": ["Telegram"],
                "materialize_count": 2,
            },
            days=3,
        )
    )

    assert len(result["plan_items"]) == 2
    assert len(result["posts"]) == 2
    assert len(fake.calls) == 3
    assert all(
        call["messages"][0]["content"].count(EXPERT_CORE_START_PREFIX) == 1
        for call in fake.calls
    )
