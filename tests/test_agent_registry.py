from app.services.agent_registry import AgentRegistry


def test_supported_agent_types_are_registered():
    assert AgentRegistry.supported_agent_types() == {
        "strategy",
        "content",
        "analytics",
        "promo",
        "trends",
    }


def test_is_supported_detects_known_and_unknown_agent_types():
    assert AgentRegistry.is_supported("content") is True
    assert AgentRegistry.is_supported("unknown") is False


def test_hard_agent_metadata():
    assert AgentRegistry.is_hard("strategy") is True
    assert AgentRegistry.is_hard("analytics") is True
    assert AgentRegistry.is_hard("content") is False
    assert AgentRegistry.is_hard("promo") is False
    assert AgentRegistry.is_hard("trends") is False


def test_get_agent_class_returns_none_for_unknown_agent_type():
    assert AgentRegistry.get_agent_class("unknown") is None
