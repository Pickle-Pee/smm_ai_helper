from __future__ import annotations

import asyncio
import json
import logging

import pytest

import app.agents.base as base_module
from app.agents.base import BaseAgent
from app.agents.analytics_agent import AnalyticsAgent
from app.agents.content_agent import ContentAgent
from app.agents.promo_agent import PromoAgent
from app.agents.strategy_agent import StrategyAgent
from app.agents.trends_agent import TrendsAgent
from app.presenters import format_agent_result
from app.services.agent_output_builder import AgentOutputBuilder
from app.services.agent_registry import AgentRegistry
from app.services.expert_instruction_composer import ExpertInstructionComposer
from app.services.task_pipeline import TaskPipelineService
from app.services.task_session_service import TaskSessionState
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


def test_corrupted_core_stops_base_agent_before_model_call(monkeypatch):
    fake = OpenAICallFake(["must not be used"])
    monkeypatch.setattr(base_module, "openai_chat", fake)
    monkeypatch.setattr(
        base_module,
        "_instruction_composer",
        ExpertInstructionComposer(core_loader=lambda _version: "CORRUPTED BUT NONEMPTY"),
    )

    with pytest.raises(Exception, match="Invalid Expert Core"):
        asyncio.run(DummyAgent().llm_text("USER MATERIAL"))

    assert len(fake.calls) == 0


AGENT_EXECUTION_CASES = (
    {
        "agent_type": "strategy",
        "agent_class": StrategyAgent,
        "responses": [{
            "assumptions": ["assumption"],
            "summary": {"north_star_metric": "sales", "main_bullets": ["focus"]},
            "positioning": {"core_message": "clear value"},
            "segments": [], "channels": [], "content_rubrics": [], "offers": [],
            "creative_angles": [], "first_7_days_plan": [], "risks_and_limits": [],
        }],
        "expected_keys": {"structured", "summary_text", "full_strategy"},
        "schema_fragment": '"north_star_metric"',
        "presenter_fragment": "NORTH STAR",
        "kwargs": {},
    },
    {
        "agent_type": "content",
        "agent_class": ContentAgent,
        "responses": [
            [{"date": "2026-08-24", "channel": "Telegram", "format": "пост", "topic": "one"}],
            {"title": "Post title", "hook": "Hook", "body": "Body", "cta": "Act", "hashtags": []},
        ],
        "expected_keys": {"plan_items", "posts", "raw_plan_markdown"},
        "schema_fragment": '"funnel_stage"',
        "presenter_fragment": "Контент-план",
        "kwargs": {"days": 3},
    },
    {
        "agent_type": "analytics",
        "agent_class": AnalyticsAgent,
        "responses": [{
            "has_metrics": True, "metrics_plan": [], "data_missing": [],
            "diagnosis": [], "benchmarks": [],
            "next_steps": [{"step": "Measure", "impact": "sales", "effort": "low", "how_to_do": "UTM"}],
            "report_template": {"frequency": "weekly", "fields": []},
        }],
        "expected_keys": {"has_metrics", "metrics_plan", "data_missing", "diagnosis", "benchmarks", "next_steps", "report_template"},
        "schema_fragment": '"metrics_plan"',
        "presenter_fragment": "План действий",
        "kwargs": {},
    },
    {
        "agent_type": "promo",
        "agent_class": PromoAgent,
        "responses": [{
            "assumptions": [], "overall_approach": ["test carefully"],
            "campaign_structure": [], "hypotheses": [], "testing_plan": {},
        }],
        "expected_keys": {"assumptions", "overall_approach", "campaign_structure", "hypotheses", "testing_plan"},
        "schema_fragment": '"campaign_structure"',
        "presenter_fragment": "Подход к рекламе",
        "kwargs": {},
    },
    {
        "agent_type": "trends",
        "agent_class": TrendsAgent,
        "responses": [{
            "assumptions": [], "format_trends": [], "content_trends": [],
            "engagement_mechanics": [],
            "experiment_roadmap": [{"experiment_name": "Test format", "hypothesis": "retention rises", "channel": "Telegram", "format": "post", "duration_days": 7}],
            "do_not_do": [],
        }],
        "expected_keys": {"assumptions", "format_trends", "content_trends", "engagement_mechanics", "experiment_roadmap", "do_not_do"},
        "schema_fragment": '"experiment_roadmap"',
        "presenter_fragment": "Эксперименты",
        "kwargs": {},
    },
)


@pytest.mark.parametrize("case", AGENT_EXECUTION_CASES, ids=lambda case: case["agent_type"])
def test_actual_agent_runs_preserve_specific_contracts(monkeypatch, case):
    fake = OpenAICallFake([json.dumps(item, ensure_ascii=False) for item in case["responses"]])
    monkeypatch.setattr(base_module, "openai_chat", fake)
    brief = {"task_description": "test", "channels": ["Telegram"], "materialize_count": 1}

    raw_result = asyncio.run(case["agent_class"]().run(brief, **case["kwargs"]))

    assert set(raw_result) == case["expected_keys"]
    assert len(fake.calls) == len(case["responses"])
    assert all(call["messages"][0]["content"].count(EXPERT_CORE_START_PREFIX) == 1 for call in fake.calls)
    assert case["schema_fragment"] in fake.calls[0]["messages"][0]["content"]
    presented = format_agent_result(case["agent_type"], raw_result)
    assert case["presenter_fragment"] in presented
    public_result = AgentOutputBuilder.build(case["agent_type"], raw_result)
    assert set(public_result) == {"content", "format", "assumptions", "confidence", "warnings"}
    assert public_result["format"] == "markdown"
    assert isinstance(public_result["content"], str)
    serialized = json.dumps(public_result, ensure_ascii=False)
    assert "expert_core_version" not in serialized
    assert EXPERT_CORE_START_PREFIX not in serialized
    assert "component_identities" not in serialized


class QCCallFake:
    def __init__(self):
        self.calls = []

    async def find_issues(self, task_description, content):
        self.calls.append((task_description, content))
        return []


def test_content_task_path_keeps_generation_and_qc_call_counts(monkeypatch):
    plan = [
        {"date": "2026-08-24", "channel": "Telegram", "format": "пост", "topic": "one"},
        {"date": "2026-08-25", "channel": "Telegram", "format": "пост", "topic": "two"},
    ]
    post = {"title": "Title", "hook": "Hook", "body": "Body", "cta": "Act", "hashtags": []}
    generation_fake = OpenAICallFake([json.dumps(plan), json.dumps(post), json.dumps(post)])
    monkeypatch.setattr(base_module, "openai_chat", generation_fake)
    qc_fake = QCCallFake()
    service = TaskPipelineService()
    service.qc_service = qc_fake
    session = TaskSessionState(
        session_id="session-1", agent_type="content", task_description="Make content",
        mode="text", answers={"days": 3, "materialize_count": 2},
        request_id="request-1", user_id="user-1",
    )

    result = asyncio.run(service._run_agent_with_qc(
        session_state=session,
        decision={"model": "model-light", "max_output_tokens": 2000, "needs_qc": True},
    ))

    assert len(generation_fake.calls) == 3
    assert len(qc_fake.calls) == 1
    assert all(call["messages"][0]["content"].count(EXPERT_CORE_START_PREFIX) == 1 for call in generation_fake.calls)
    assert result["format"] == "markdown"
    assert result["warnings"] == []


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
