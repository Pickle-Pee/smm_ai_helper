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


def _assert_exact_type(value, expected_type):
    assert type(value) is expected_type


def _assert_string_list(value):
    _assert_exact_type(value, list)
    assert value
    assert all(type(item) is str and item for item in value)


def _assert_string_fields(value, keys):
    for key in keys:
        _assert_exact_type(value[key], str)


def _assert_strategy_contract(result):
    assert set(result) == {"structured", "summary_text", "full_strategy"}
    _assert_exact_type(result["structured"], dict)
    _assert_exact_type(result["summary_text"], str)
    _assert_exact_type(result["full_strategy"], str)
    data = result["structured"]
    assert set(data) == {"assumptions", "summary", "positioning", "segments", "funnel", "offers", "channels", "content_rubrics", "creative_angles", "first_7_days_plan", "risks_and_limits"}
    _assert_string_list(data["assumptions"])
    for key in ("segments", "offers", "channels", "content_rubrics", "creative_angles", "first_7_days_plan", "risks_and_limits"):
        _assert_exact_type(data[key], list)
    _assert_exact_type(data["summary"], dict)
    _assert_exact_type(data["positioning"], dict)
    _assert_exact_type(data["funnel"], dict)
    assert set(data["summary"]) == {"north_star_metric", "main_bullets"}
    _assert_exact_type(data["summary"]["north_star_metric"], str)
    _assert_string_list(data["summary"]["main_bullets"])
    assert set(data["positioning"]) == {"core_message", "utp", "reasons_to_believe", "tone_of_voice", "do_not_say"}
    _assert_exact_type(data["positioning"]["core_message"], str)
    for key in ("utp", "reasons_to_believe", "tone_of_voice", "do_not_say"):
        _assert_string_list(data["positioning"][key])
    segment = data["segments"][0]
    assert set(segment) == {"name", "short_profile", "pains", "triggers", "objections", "message_map"}
    assert set(segment["message_map"]) == {"hook_angles", "proof_points", "cta_examples"}
    for key in ("name", "short_profile"):
        _assert_exact_type(segment[key], str)
    for key in ("pains", "triggers", "objections"):
        _assert_string_list(segment[key])
    for value in segment["message_map"].values():
        _assert_string_list(value)
    assert set(data["funnel"]) == {"awareness", "consideration", "conversion", "retention"}
    for stage in data["funnel"].values():
        assert set(stage) == {"goal", "content_types", "examples"}
        _assert_exact_type(stage["goal"], str)
        _assert_string_list(stage["content_types"])
        _assert_string_list(stage["examples"])
    assert set(data["offers"][0]) == {"name", "what_user_gets", "for_whom", "friction_reducers", "cta_examples"}
    _assert_string_fields(data["offers"][0], ("name", "what_user_gets", "for_whom"))
    _assert_string_list(data["offers"][0]["friction_reducers"])
    _assert_string_list(data["offers"][0]["cta_examples"])
    assert set(data["channels"][0]) == {"name", "role", "cadence", "content_focus", "conversion_path"}
    _assert_string_fields(data["channels"][0], ("name", "role", "cadence", "conversion_path"))
    _assert_string_list(data["channels"][0]["content_focus"])
    assert set(data["content_rubrics"][0]) == {"name", "goal", "examples"}
    _assert_string_fields(data["content_rubrics"][0], ("name", "goal"))
    _assert_string_list(data["content_rubrics"][0]["examples"])
    assert set(data["creative_angles"][0]) == {"angle", "when_to_use", "example_headline", "example_text"}
    _assert_string_fields(data["creative_angles"][0], ("angle", "when_to_use", "example_headline", "example_text"))
    day = data["first_7_days_plan"][0]
    assert set(day) == {"day", "channel", "format", "topic", "goal", "key_points", "cta"}
    _assert_exact_type(day["day"], int)
    _assert_string_fields(day, ("channel", "format", "topic", "goal", "cta"))
    _assert_string_list(day["key_points"])
    _assert_string_list(data["risks_and_limits"])


def _assert_content_contract(result):
    assert set(result) == {"plan_items", "posts", "raw_plan_markdown"}
    _assert_exact_type(result["plan_items"], list)
    _assert_exact_type(result["posts"], list)
    _assert_exact_type(result["raw_plan_markdown"], str)
    item = result["plan_items"][0]
    assert set(item) == {"date", "channel", "format", "content_type", "funnel_stage", "rubric", "topic", "goal", "hook", "promise", "key_points", "cta_type", "cta"}
    for key, value in item.items():
        _assert_string_list(value) if key == "key_points" else _assert_exact_type(value, str)
    post_item = result["posts"][0]
    assert set(post_item) == {"plan_item", "post"}
    assert post_item["plan_item"] == item
    post = post_item["post"]
    assert set(post) == {"title", "hook", "body", "cta", "hashtags", "notes_for_design", "full_text"}
    for key in ("title", "hook", "body", "cta", "full_text"):
        _assert_exact_type(post[key], str)
    _assert_string_list(post["hashtags"])
    _assert_string_list(post["notes_for_design"])


def _assert_analytics_contract(result):
    assert set(result) == {"has_metrics", "metrics_plan", "data_missing", "diagnosis", "benchmarks", "next_steps", "report_template"}
    _assert_exact_type(result["has_metrics"], bool)
    for key in ("metrics_plan", "data_missing", "diagnosis", "benchmarks", "next_steps"):
        _assert_exact_type(result[key], list)
    _assert_exact_type(result["report_template"], dict)
    metric_plan = result["metrics_plan"][0]
    assert set(metric_plan) == {"channel", "scope", "metrics"}
    _assert_string_fields(metric_plan, ("channel", "scope"))
    _assert_exact_type(metric_plan["metrics"], list)
    metric = metric_plan["metrics"][0]
    assert set(metric) == {"name", "how_to_calc", "data_source", "why_important", "interpretation"}
    assert all(type(value) is str for value in metric.values())
    _assert_string_list(result["data_missing"])
    assert set(result["diagnosis"][0]) == {"finding", "why_it_matters", "likely_causes"}
    _assert_string_fields(result["diagnosis"][0], ("finding", "why_it_matters"))
    _assert_string_list(result["diagnosis"][0]["likely_causes"])
    assert set(result["benchmarks"][0]) == {"metric", "guidance", "notes"}
    _assert_string_fields(result["benchmarks"][0], ("metric", "guidance", "notes"))
    assert set(result["next_steps"][0]) == {"step", "impact", "effort", "how_to_do"}
    assert all(type(value) is str for value in result["next_steps"][0].values())
    assert set(result["report_template"]) == {"frequency", "fields"}
    _assert_exact_type(result["report_template"]["frequency"], str)
    _assert_string_list(result["report_template"]["fields"])


def _assert_promo_contract(result):
    assert set(result) == {"assumptions", "overall_approach", "campaign_structure", "hypotheses", "testing_plan"}
    _assert_string_list(result["assumptions"])
    _assert_string_list(result["overall_approach"])
    _assert_exact_type(result["campaign_structure"], list)
    _assert_exact_type(result["hypotheses"], list)
    _assert_exact_type(result["testing_plan"], dict)
    campaign = result["campaign_structure"][0]
    assert set(campaign) == {"channel", "objective", "tracking", "layers"}
    _assert_string_fields(campaign, ("channel", "objective"))
    _assert_exact_type(campaign["tracking"], dict)
    _assert_exact_type(campaign["layers"], list)
    assert set(campaign["tracking"]) == {"utm", "pixel", "events"}
    _assert_exact_type(campaign["tracking"]["utm"], bool)
    _assert_exact_type(campaign["tracking"]["pixel"], str)
    _assert_string_list(campaign["tracking"]["events"])
    layer = campaign["layers"][0]
    assert set(layer) == {"name", "audience", "exclusions", "formats", "offer_type", "creative_notes", "landing_next_step"}
    for key in ("exclusions", "formats", "creative_notes"):
        _assert_string_list(layer[key])
    _assert_string_fields(layer, ("name", "audience", "offer_type", "landing_next_step"))
    hypothesis = result["hypotheses"][0]
    assert set(hypothesis) == {"name", "segment", "problem_trigger", "offer", "format", "angle", "example_creative", "expected_metric", "success_criteria", "failure_criteria"}
    assert set(hypothesis["example_creative"]) == {"headline", "primary_text", "cta"}
    _assert_string_fields(hypothesis, ("name", "segment", "problem_trigger", "offer", "format", "angle", "expected_metric", "success_criteria", "failure_criteria"))
    _assert_string_fields(hypothesis["example_creative"], ("headline", "primary_text", "cta"))
    plan = result["testing_plan"]
    assert set(plan) == {"budget_split", "budget_per_hypothesis", "duration", "minimum_data", "stop_rules", "scale_rules", "notes"}
    assert set(plan["minimum_data"]) == {"clicks", "leads"}
    _assert_string_fields(plan, ("budget_split", "budget_per_hypothesis", "duration"))
    assert all(type(value) is str for value in plan["minimum_data"].values())
    for key in ("stop_rules", "scale_rules", "notes"):
        _assert_string_list(plan[key])


def _assert_trends_contract(result):
    assert set(result) == {"assumptions", "format_trends", "content_trends", "engagement_mechanics", "experiment_roadmap", "do_not_do"}
    _assert_string_list(result["assumptions"])
    for key in ("format_trends", "content_trends", "engagement_mechanics", "experiment_roadmap", "do_not_do"):
        _assert_exact_type(result[key], list)
    trend = result["format_trends"][0]
    assert set(trend) == {"format", "pattern", "why_it_works", "suitable_for_brand", "how_to_use", "example_ideas", "measurement"}
    _assert_exact_type(trend["suitable_for_brand"], bool)
    _assert_string_fields(trend, ("format", "pattern", "why_it_works", "how_to_use"))
    _assert_string_list(trend["example_ideas"])
    assert set(trend["measurement"]) == {"primary_metric", "success_signal"}
    _assert_string_fields(trend["measurement"], ("primary_metric", "success_signal"))
    content = result["content_trends"][0]
    assert set(content) == {"pattern", "description", "fit_for_brand", "examples_for_brand", "risks", "mitigation"}
    for key in ("examples_for_brand", "risks", "mitigation"):
        _assert_string_list(content[key])
    _assert_string_fields(content, ("pattern", "description", "fit_for_brand"))
    mechanic = result["engagement_mechanics"][0]
    assert set(mechanic) == {"mechanic", "idea_for_brand", "script", "expected_effect", "measurement"}
    _assert_string_fields(mechanic, ("mechanic", "idea_for_brand", "script", "expected_effect", "measurement"))
    experiment = result["experiment_roadmap"][0]
    assert set(experiment) == {"experiment_name", "hypothesis", "channel", "format", "steps", "duration_days", "how_to_measure"}
    _assert_string_list(experiment["steps"])
    _assert_exact_type(experiment["duration_days"], int)
    _assert_string_fields(experiment, ("experiment_name", "hypothesis", "channel", "format"))
    assert set(experiment["how_to_measure"]) == {"baseline", "primary_metric", "success_criteria", "stop_criteria"}
    assert all(type(value) is str for value in experiment["how_to_measure"].values())
    _assert_string_list(result["do_not_do"])


AGENT_EXECUTION_CASES = (
    {
        "agent_type": "strategy",
        "agent_class": StrategyAgent,
        "responses": [{
            "assumptions": ["assumption"],
            "summary": {"north_star_metric": "sales", "main_bullets": ["focus"]},
            "positioning": {"core_message": "clear value", "utp": ["Fast insight"], "reasons_to_believe": ["Weekly report"], "tone_of_voice": ["Direct"], "do_not_say": ["Guaranteed"]},
            "segments": [{"name": "Owners", "short_profile": "Small business owners", "pains": ["Low demand"], "triggers": ["Revenue decline"], "objections": ["No time"], "message_map": {"hook_angles": ["Find lost demand"], "proof_points": ["Tracked leads"], "cta_examples": ["Request audit"]}}],
            "funnel": {stage: {"goal": goal, "content_types": ["case study"], "examples": ["Weekly teardown"]} for stage, goal in (("awareness", "Reach"), ("consideration", "Trust"), ("conversion", "Leads"), ("retention", "Repeat sales"))},
            "offers": [{"name": "Audit", "what_user_gets": "Action plan", "for_whom": "Owners", "friction_reducers": ["Fixed scope"], "cta_examples": ["Book audit"]}],
            "channels": [{"name": "Telegram", "role": "Educate", "cadence": "Three weekly", "content_focus": ["Cases"], "conversion_path": "Post to form"}],
            "content_rubrics": [{"name": "Teardowns", "goal": "Build trust", "examples": ["Landing review"]}],
            "creative_angles": [{"angle": "Lost demand", "when_to_use": "Cold audience", "example_headline": "Where leads leak", "example_text": "Check three stages."}],
            "first_7_days_plan": [{"day": 1, "channel": "Telegram", "format": "post", "topic": "Lead leaks", "goal": "Trust", "key_points": ["Measure source"], "cta": "Save checklist"}],
            "risks_and_limits": ["Baseline is limited"],
        }],
        "schema_fragment": '"north_star_metric"',
        "presenter_fragment": "NORTH STAR",
        "kwargs": {},
        "assert_contract": _assert_strategy_contract,
    },
    {
        "agent_type": "content",
        "agent_class": ContentAgent,
        "responses": [
            [{"date": "2026-08-24", "channel": "Telegram", "format": "пост", "content_type": "экспертный", "funnel_stage": "consideration", "rubric": "Разбор", "topic": "Lead audit", "goal": "доверие", "hook": "Where leads leak", "promise": "Three checks", "key_points": ["Check UTM", "Compare cohorts"], "cta_type": "save", "cta": "Save checklist"}],
            {"title": "Lead audit", "hook": "Where leads leak", "body": "Run three checks.", "cta": "Save checklist", "hashtags": ["#analytics"], "notes_for_design": ["Use a funnel diagram"]},
        ],
        "schema_fragment": '"funnel_stage"',
        "presenter_fragment": "Контент-план",
        "kwargs": {"days": 3},
        "assert_contract": _assert_content_contract,
    },
    {
        "agent_type": "analytics",
        "agent_class": AnalyticsAgent,
        "responses": [{
            "has_metrics": True,
            "metrics_plan": [{"channel": "Telegram", "scope": "воронка", "metrics": [{"name": "CTR", "how_to_calc": "clicks / views", "data_source": "UTM report", "why_important": "Shows intent", "interpretation": "Compare weekly"}]}],
            "data_missing": ["Lead quality"],
            "diagnosis": [{"finding": "Clicks do not convert", "why_it_matters": "Acquisition is inefficient", "likely_causes": ["Offer mismatch"]}],
            "benchmarks": [{"metric": "CTR", "guidance": "Compare to prior week", "notes": "Segment by format"}],
            "next_steps": [{"step": "Measure", "impact": "sales", "effort": "low", "how_to_do": "UTM"}],
            "report_template": {"frequency": "weekly", "fields": ["date", "views", "clicks"]},
        }],
        "schema_fragment": '"metrics_plan"',
        "presenter_fragment": "План действий",
        "kwargs": {},
        "assert_contract": _assert_analytics_contract,
    },
    {
        "agent_type": "promo",
        "agent_class": PromoAgent,
        "responses": [{
            "assumptions": ["Baseline comes from week one"], "overall_approach": ["Test one variable at a time"],
            "campaign_structure": [{"channel": "Telegram", "objective": "leads", "tracking": {"utm": True, "pixel": "Not applicable", "events": ["click", "lead"]}, "layers": [{"name": "cold", "audience": "Owners seeking demand", "exclusions": ["Existing clients"], "formats": ["native_post"], "offer_type": "demo", "creative_notes": ["Show audit output"], "landing_next_step": "Short lead form"}]}],
            "hypotheses": [{"name": "Audit offer", "segment": "Owners", "problem_trigger": "Lead decline", "offer": "Free audit", "format": "native", "angle": "Find leaks", "example_creative": {"headline": "Find lost leads", "primary_text": "Audit the funnel.", "cta": "Request"}, "expected_metric": "CPL", "success_criteria": "Beats baseline", "failure_criteria": "Worse after minimum data"}],
            "testing_plan": {"budget_split": "Equal split", "budget_per_hypothesis": "Enough for 100 clicks", "duration": "7 days", "minimum_data": {"clicks": "100", "leads": "10"}, "stop_rules": ["Stop below baseline after minimum data"], "scale_rules": ["Scale stable winners gradually"], "notes": ["Watch creative fatigue"]},
        }],
        "schema_fragment": '"campaign_structure"',
        "presenter_fragment": "Подход к рекламе",
        "kwargs": {},
        "assert_contract": _assert_promo_contract,
    },
    {
        "agent_type": "trends",
        "agent_class": TrendsAgent,
        "responses": [{
            "assumptions": ["Telegram is primary"],
            "format_trends": [{"format": "post", "pattern": "Concise teardown", "why_it_works": "Immediate utility", "suitable_for_brand": True, "how_to_use": "Review one funnel weekly", "example_ideas": ["Landing teardown"], "measurement": {"primary_metric": "saves", "success_signal": "Above baseline"}}],
            "content_trends": [{"pattern": "Build in public", "description": "Show decisions", "fit_for_brand": "Demonstrates expertise", "examples_for_brand": ["Campaign diary"], "risks": ["Oversharing"], "mitigation": ["Anonymize data"]}],
            "engagement_mechanics": [{"mechanic": "poll", "idea_for_brand": "Choose next teardown", "script": "Offer three choices", "expected_effect": "More comments", "measurement": "Votes versus baseline"}],
            "experiment_roadmap": [{"experiment_name": "Test format", "hypothesis": "If teardowns are concise, retention rises because value is immediate", "channel": "Telegram", "format": "post", "steps": ["Record baseline", "Publish three tests"], "duration_days": 7, "how_to_measure": {"baseline": "Prior five posts", "primary_metric": "retention", "success_criteria": "Improves versus baseline", "stop_criteria": "Declines for three posts"}}],
            "do_not_do": ["Copy trends without brand fit"],
        }],
        "schema_fragment": '"experiment_roadmap"',
        "presenter_fragment": "Эксперименты",
        "kwargs": {},
        "assert_contract": _assert_trends_contract,
    },
)


@pytest.mark.parametrize("case", AGENT_EXECUTION_CASES, ids=lambda case: case["agent_type"])
def test_actual_agent_runs_preserve_specific_contracts(monkeypatch, case):
    fake = OpenAICallFake([json.dumps(item, ensure_ascii=False) for item in case["responses"]])
    monkeypatch.setattr(base_module, "openai_chat", fake)
    brief = {"task_description": "test", "channels": ["Telegram"], "materialize_count": 1}

    raw_result = asyncio.run(case["agent_class"]().run(brief, **case["kwargs"]))

    case["assert_contract"](raw_result)
    assert len(fake.calls) == len(case["responses"])
    assert all(call["messages"][0]["content"].count(EXPERT_CORE_START_PREFIX) == 1 for call in fake.calls)
    assert case["schema_fragment"] in fake.calls[0]["messages"][0]["content"]
    presented = format_agent_result(case["agent_type"], raw_result)
    assert case["presenter_fragment"] in presented
    public_result = AgentOutputBuilder.build(case["agent_type"], raw_result)
    assert set(public_result) == {"content", "format", "assumptions", "confidence", "warnings"}
    assert public_result["format"] == "markdown"
    _assert_exact_type(public_result["content"], str)
    _assert_exact_type(public_result["format"], str)
    _assert_exact_type(public_result["assumptions"], list)
    _assert_exact_type(public_result["confidence"], str)
    _assert_exact_type(public_result["warnings"], list)
    serialized = json.dumps(public_result, ensure_ascii=False)
    assert "expert_core_version" not in serialized
    assert EXPERT_CORE_START_PREFIX not in serialized
    assert "component_identities" not in serialized
    assert "structured" not in public_result
    assert "raw_result" not in public_result


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
