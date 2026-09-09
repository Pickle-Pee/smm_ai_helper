"""Deterministic providers for workflow integration and the offline smoke path."""
import base64
import json

from app.services.image_orchestrator import ImageOrchestrator
from app.services.url_analyzer import UrlAnalysisResult


class FakeAnalyzer:
    async def analyze(self, url):
        return UrlAnalysisResult([url], [{"url": url, "final_url": url, "ok": True,
            "title": "Конкурент", "h1": ["Консультация по выбору курса"],
            "main_text_excerpt": "На странице предложена консультация по выбору учебного курса. Цена и результаты обучения не указаны."}])


class FakeImages:
    def __init__(self): self.calls = []
    async def generate(self, **kwargs):
        self.calls.append(kwargs)
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jA8sAAAAASUVORK5CYII=")
        image_id = ImageOrchestrator()._save_image(png, kwargs["user_id"])
        return {"image_ids": [image_id]}


class FakeModel:
    def __init__(self): self.calls = []
    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        step = kwargs["response_format"]["name"].removeprefix("marketing_")
        supplied = json.loads(kwargs["messages"][1]["content"])
        claim = {"text": "Небольшой тест понятного оффера может проверить интерес аудитории.",
                 "output_name": {"analysis": "observable_positioning", "creative": "creative_strategy", "mentor": "principle"}[step],
                 "kind": "HYPOTHESIS", "confidence": "LOW",
                 "evidence_ids": supplied["local_evidence_ids"][:1],
                 "parent_claim_ids": supplied["parent_claim_ids"][-1:]}
        common = {"claims": [claim], "assumptions": ["Запрос на консультацию может отражать сомнение в выборе."],
                  "limitations": ["Нет данных о конверсии и результатах клиентов."]}
        if step == "analysis":
            result = {"schema_version": "competitor_analysis.v1", "observed_positioning": "Консультация для выбора курса.",
                      "strengths": ["Понятный следующий шаг."], "weaknesses": ["На странице не видна цена."],
                      "customer_hypotheses": ["Нужна помощь с выбором."], "differentiation": ["Показать программу до консультации."],
                      "practical_brief": "Проверить оффер с открытой программой и понятным следующим шагом."}
        elif step == "creative":
            result = {"schema_version": "creative_package.v1", "hypothesis": "Открытая программа уменьшит неопределённость.",
                      "trigger": "Понятность выбора", "offer": "Познакомьтесь с программой", "headline": "Выберите свой следующий навык",
                      "cta": "Посмотреть программу", "image_brief": "Баннер с учебной программой и ясным заголовком.",
                      "scenes": [{"start_seconds": i * 5, "end_seconds": (i + 1) * 5, "visual": "Программа курса", "narration": "Посмотрите, что будете изучать.", "retention_hook": "Конкретный следующий шаг"} for i in range(3)]}
        else:
            result = {"schema_version": "mentor_explanation.v1", "principle": "Уменьшение неопределённости перед выбором.",
                      "evidence_explanation": "На исходной странице было предложение консультации; данные о цене отсутствовали.",
                      "alternative": "Сравните с общим обещанием качества без программы.",
                      "when_it_fails": ["Если основное возражение связано с ценой, а не с программой."],
                      "validation_plan": ["Сравните два оффера на сопоставимой аудитории и оцените заявки; не объявляйте причинность без подходящего дизайна теста."]}
        return json.dumps({**common, **result}, ensure_ascii=False), {"total_tokens": 0}
