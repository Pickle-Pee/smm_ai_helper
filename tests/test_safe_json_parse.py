from app.agents.utils import safe_json_parse


def test_safe_json_parse_fenced_json():
    raw = "```json\n{\"ok\": true, \"value\": 1}\n```"
    assert safe_json_parse(raw) == {"ok": True, "value": 1}


def test_safe_json_parse_prefix_suffix():
    raw = "Вот результат: {\"status\": \"ok\", \"items\": [1, 2]} спасибо!"
    assert safe_json_parse(raw) == {"status": "ok", "items": [1, 2]}
