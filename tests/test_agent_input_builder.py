from app.services.agent_input_builder import AgentInputBuilder


def test_build_includes_task_description_and_answers_in_brief():
    agent_input = AgentInputBuilder.build(
        agent_type="strategy",
        task_description="Сделай стратегию",
        answers={"audience": "эксперты", "channel": "Telegram"},
    )

    assert agent_input.brief == {
        "task_description": "Сделай стратегию",
        "audience": "эксперты",
        "channel": "Telegram",
    }
    assert agent_input.kwargs == {}


def test_build_adds_qc_issues_to_brief_when_present():
    agent_input = AgentInputBuilder.build(
        agent_type="strategy",
        task_description="Сделай стратегию",
        answers={},
        qc_issues=["Добавить конкретные шаги"],
    )

    assert agent_input.brief["qc_issues"] == ["Добавить конкретные шаги"]


def test_content_days_can_be_built_from_days_answer():
    agent_input = AgentInputBuilder.build(
        agent_type="content",
        task_description="Сделай контент-план",
        answers={"days": "14"},
    )

    assert agent_input.kwargs == {"days": 14}


def test_content_days_can_be_built_from_period_answer():
    agent_input = AgentInputBuilder.build(
        agent_type="content",
        task_description="Сделай контент-план",
        answers={"period": "7"},
    )

    assert agent_input.kwargs == {"days": 7}


def test_invalid_content_period_is_ignored():
    agent_input = AgentInputBuilder.build(
        agent_type="content",
        task_description="Сделай контент-план",
        answers={"period": "две недели"},
    )

    assert agent_input.kwargs == {}
