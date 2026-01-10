from __future__ import annotations


INTENT_KEYWORDS = {
    "content": ["контент", "пост", "план", "текст", "рубрика", "сторис"],
    "strategy": ["стратег", "ворон", "позиционир", "целевая", "цели"],
    "audit": ["аудит", "разбор", "провер", "оценка"],
    "ads": ["реклама", "таргет", "ads", "продвижение", "объявления"],
    "analysis": ["аналит", "метрик", "отчет", "данные", "рост", "падение"],
}


def detect_intent(text: str) -> str:
    lowered = text.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(word in lowered for word in keywords):
            return intent
    return "other"
