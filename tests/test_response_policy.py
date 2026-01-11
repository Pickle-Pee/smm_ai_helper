from app.services.response_policy import enforce_policy


def test_single_follow_up_question():
    response = {
        "reply": "Ok",
        "follow_up_question": "Какой продукт? И какой бюджет?",
        "actions": [{"type": "suggestion", "text": "Сделать подробнее"}],
    }
    updated = enforce_policy(response)
    assert updated["follow_up_question"].count("?") == 1
