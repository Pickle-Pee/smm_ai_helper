"""Deterministic Russian presentation of the public HTTP contract, plain text only."""
from bot import copilot_contracts as dto

SECTIONS = {
    "strategic_diagnosis": "Стратегический диагноз",
    "main_growth_constraint": "Главное ограничение роста",
    "strategic_priorities": "Стратегические приоритеты",
    "trade_offs": "Компромиссы",
    "resource_priorities": "Приоритеты ресурсов",
    "strategic_bets": "Стратегические ставки",
    "roadmap": "План действий",
    "risks": "Риски",
    "decision_triggers": "Условия пересмотра решений",
}
FIELDS = {
    "business_goal": "Какого бизнес-результата вы хотите достичь?",
    "product": "Какой у вас продукт или услуга?",
    "product_or_category": "Какой продукт или категорию исследуем?",
    "target_or_target_hypothesis": "Кто ваша целевая аудитория?",
    "target_segment": "Какой сегмент аудитории исследуем?",
    "target": "Кто ваша целевая аудитория?",
    "customer_job_or_need": "Какую задачу или потребность клиента решает продукт?",
    "relevant_alternative": "Чем клиент пользуется вместо вашего продукта?",
    "product_truth": "Какие свойства продукта вы можете подтвердить?",
    "existing_proof": "Какие есть подтверждения: результаты, отзывы, исследования?",
    "geographic_scope": "В какой стране или регионе работает бизнес?",
    "geography": "В какой стране или регионе работает бизнес?",
    "economics": "Какие известны выручка, затраты и маржинальность?",
    "message": "Какую главную мысль должен передать пост?",
    "tone": "Какой тон общения использовать?",
    "competitor_or_category_scope": "Пришлите ссылку на конкурента и укажите её роль кнопкой.",
    "one_competitor_url": "Пришлите одну ссылку на конкурента и укажите её роль кнопкой.",
    "up_to_three_valid_competitor_urls": "Пришлите до трёх ссылок на конкурентов и укажите их роли кнопками.",
    "budget": "Какой бюджет?",
    "cpl": "Какова стоимость одного лида?",
    "cpc": "Какова стоимость одного клика?",
    "traffic": "Сколько посещений?",
    "conversion_rate_percent": "Какова конверсия в процентах?",
    "required_leads": "Сколько лидов нужно получить?",
}
ALIASES = {"target_or_target_hypothesis": "target", "target_segment": "target",
           "product_or_category": "product", "geographic_scope": "geography"}
TOPICS = dict(zip(
    "competitor_set direct_competitors indirect_competitors substitutes observable_positioning offers proof strengths weaknesses patterns contradictions market_gaps differentiation_hypotheses category frame_of_reference target demand_context JTBD_frame value_proposition differentiation points_of_parity points_of_difference RTB positioning_statement USP_directions offer message_hierarchy claim_risks validation_plan market_definition category_structure market_size_if_supported demand_drivers demand_barriers segments segment_attractiveness JTBD CEP alternatives audience_findings market_opportunities white_spaces research_gaps".split(),
    ["Конкуренты", "Прямые конкуренты", "Косвенные конкуренты", "Заменители", "Наблюдаемое позиционирование", "Предложения", "Подтверждения", "Сильные стороны", "Слабые стороны", "Закономерности", "Противоречия", "Пробелы рынка", "Гипотезы отличий", "Категория", "Контекст выбора", "Аудитория", "Контекст спроса", "Задача клиента", "Ценность", "Отличия", "Общие черты", "Отличительные черты", "Основания доверия", "Позиционирование", "Направления УТП", "Предложение", "Иерархия сообщений", "Риски утверждений", "План проверки", "Определение рынка", "Структура категории", "Оценка размера рынка", "Драйверы спроса", "Барьеры спроса", "Сегменты", "Привлекательность сегментов", "Задачи клиентов", "Ситуации покупки", "Альтернативы", "Наблюдения об аудитории", "Возможности рынка", "Свободные ниши", "Пробелы исследования"], strict=True))
TRANSLATIONS = {
    "Additional context or an accessible source is required.": "Нужны дополнительные сведения или доступный источник.",
    "Review the supplied context and sources, then submit a new request key.": "Проверьте сведения и источники, затем начните новый запрос: /new",
    "Market research was not supplied.": "Источники исследования рынка не предоставлены.",
    "Competitor research was not supplied.": "Источники исследования конкурентов не предоставлены.",
    "Only one competitor was analyzed.": "Проанализирован только один конкурент.",
    "Economics are unavailable; profitability and affordability remain unknown.": "Данных об экономике нет: прибыльность и доступность ресурсов не оценены.",
    "One competitor analysis is unavailable.": "Анализ одного из конкурентов недоступен.",
    "Market research is unavailable.": "Исследование рынка недоступно.",
    "Experiments are unavailable.": "Эксперименты недоступны.",
    "An optional result is unavailable.": "Один из дополнительных результатов недоступен.",
    "Evidence coverage is limited.": "Исследование охватывает не все источники.",
    "Public page; published assertions are not independently verified": "Публичная страница; её утверждения независимо не проверены",
    "Supplied business context; not independently verified": "Предоставленные сведения о бизнесе; независимо не проверены",
    "Caller-supplied source excerpt; not independently verified": "Предоставленная выдержка из источника; независимо не проверена",
    "All monetary inputs use the same caller-selected currency; no currency conversion or fees.": "Все суммы в одной валюте; обмен валют и комиссии не учитываются.",
    "Constant supplied unit costs and conversion rate; 34 significant decimal digits, fractional expected counts, no rounding to people.": "Стоимость и конверсия считаются постоянными. Результат — ожидаемое число, без округления до целых людей.",
}


def human(text):
    return TRANSLATIONS.get(text, text)


def bullets(values):
    return "\n".join("• " + human(value) for value in dict.fromkeys(values))


def limits(values):
    return ["⚠ Ограничения\n" + bullets(values)] if values else []


def calculation(value: dto.Calculation) -> list[str]:
    labels = dict(budget="Бюджет", cpc="Стоимость клика", cpl="Стоимость лида", traffic="Посещения",
        conversion_rate_percent="Конверсия, %", required_leads="Нужно лидов", clicks="Клики", leads="Лиды",
        required_traffic="Нужное число посещений", required_budget="Нужный бюджет")
    formula = {"budget/cpl": "Бюджет делим на стоимость лида.",
        "budget/cpc*rate": "Бюджет делим на стоимость клика и умножаем на конверсию / 100.",
        "traffic*rate": "Число посещений умножаем на конверсию / 100.",
        "required_leads/rate": "Нужное число лидов делим на конверсию / 100.",
        "required_leads*cpl": "Нужное число лидов умножаем на стоимость лида."}[value.formula]
    inputs = "\n".join(f"{labels[k]}: {v}" for k, v in value.inputs.model_dump().items() if v is not None)
    outputs = "\n".join(f"{labels[k]}: {v}" for k, v in value.outputs.model_dump().items() if v is not None)
    return [f"Расчёт\n{inputs}\n\n{formula}\n\nРезультат\n{outputs}"] + (
        ["Допущения\n" + bullets(value.assumptions)] if value.assumptions else [])


def module(value: dto.Post | dto.Findings) -> list[str]:
    if isinstance(value, dto.Post):
        return [value.headline, value.body, "Призыв к действию\n" + value.cta] + limits(value.limitations)
    messages = [{"competitor_analysis": "Анализ конкурента", "market_analysis": "Анализ рынка",
                 "positioning": "Позиционирование"}[value.kind]]
    kinds = {"OBSERVATION": "Наблюдение", "INFERENCE": "Вывод", "HYPOTHESIS": "Гипотеза", "RECOMMENDATION": "Рекомендация"}
    confidence = {"UNKNOWN": "уверенность не оценена", "LOW": "низкая уверенность", "MEDIUM": "средняя уверенность", "HIGH": "высокая уверенность"}
    for item in value.findings:
        messages.append(f"{TOPICS.get(item.topic, 'Вывод исследования')}\n{item.text}\n"
                        f"{kinds[item.kind]}, {confidence[item.confidence]}.")
    if value.sources:
        messages.append("Источники\n" + bullets([human(s.label) + (f"\n{s.url}" if s.url else "") for s in value.sources]))
    return messages + limits(value.limitations)


def run(value: dto.RunResponse) -> list[str]:
    if value.status == dto.RunStatus.QUEUED:
        return ["Запрос поставлен в работу."]
    if value.status == dto.RunStatus.RUNNING:
        return ["Стратегия собирается."]
    if value.status == dto.RunStatus.FAILED:
        return ["Не удалось завершить запрос. Можно попробовать снова."]
    if value.status == dto.RunStatus.BLOCKED:
        return ["Нужно уточнить запрос.", human(value.failure.message), *(human(a) for a in value.failure.actions)] if value.failure else ["Нужно уточнить запрос. Начните новый запрос: /new"]
    messages = ["Стратегия готова." if value.strategy else "Результат готов."]
    if value.strategy:
        for key, label in SECTIONS.items():
            section = getattr(value.strategy, key)
            messages.append(f"{label}\n{section.text}\n{bullets(section.items)}")
    if value.experiments:
        messages.append("Эксперименты — отдельный план проверки гипотез")
        for experiment in value.experiments.designs:
            messages.append(f"Гипотеза: {experiment.hypothesis}\nМетрика: {experiment.target_metric}\n"
                f"Изменение: {experiment.intervention}\nОжидаемый сигнал: {experiment.expected_signal}\n"
                f"Условие неудачи: {experiment.failure_condition}\n"
                f"Нужные данные:\n{bullets(experiment.minimum_required_inputs)}\n"
                f"Время и ресурсы:\n{bullets(experiment.time_resource_constraints)}")
    for detail in value.details:
        messages.extend(module(detail))
    coverage = value.evidence_coverage
    if coverage:
        messages.append(f"Исследование: {coverage.competitors_accepted} из {coverage.competitors_supplied} конкурентов обработаны.")
    all_limits = [*value.limitations, *(value.strategy.limitations if value.strategy else []),
        *(value.experiments.limitations if value.experiments else []), *(coverage.limitations if coverage else [])]
    if value.status == dto.RunStatus.COMPLETED_WITH_LIMITATIONS and not all_limits:
        all_limits.append("Часть исследования недоступна. Учитывайте это при принятии решений.")
    return messages + limits(all_limits)
