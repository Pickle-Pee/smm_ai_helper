from app.schemas import ChatMessageResponse


def test_chat_response_schema():
    payload = {
        "reply": "Ответ",
        "follow_up_question": None,
        "actions": [{"type": "suggestion", "text": "Сделать подробнее"}],
        "debug": {"intent": "content", "used_url": False},
    }
    parsed = ChatMessageResponse(**payload)
    assert parsed.reply == "Ответ"
