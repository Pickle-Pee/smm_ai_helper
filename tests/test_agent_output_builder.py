from app.services.agent_output_builder import AgentOutputBuilder


def test_build_normalizes_raw_agent_result():
    output = AgentOutputBuilder.build(
        agent_type="content",
        raw_result={
            "user_answer": "Готовый ответ",
            "assumptions": ["допущение"],
            "confidence": "high",
            "warnings": ["warning"],
        },
    )

    assert output == {
        "content": "Готовый ответ",
        "format": "markdown",
        "assumptions": ["допущение"],
        "confidence": "high",
        "warnings": ["warning"],
    }


def test_build_uses_safe_defaults_when_optional_fields_are_missing():
    output = AgentOutputBuilder.build(
        agent_type="content",
        raw_result={"user_answer": "Готовый ответ"},
    )

    assert output == {
        "content": "Готовый ответ",
        "format": "markdown",
        "assumptions": [],
        "confidence": "medium",
        "warnings": [],
    }
