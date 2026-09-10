"""Render the structured artifact; keep source/assumption limits visible."""


def split_text(text: str, limit=3500):
    chunks, buffer, units = [], [], 0
    for char in text:
        cost = 2 if ord(char) > 0xFFFF else 1
        if units + cost > limit:
            chunks.append("".join(buffer))
            buffer, units = [], 0
        buffer.append(char)
        units += cost
    if buffer:
        chunks.append("".join(buffer))
    return chunks or ["Готово."]


def render_artifact(artifact):
    result, step = artifact["result"], artifact["step"]
    title = {"analysis": "Анализ конкурента", "creative": "Коммерческий креативный пакет", "mentor": "Почему предложено это решение"}[step]
    sections = [title]
    fields = {
        "analysis": [("observed_positioning", "Наблюдаемое позиционирование"), ("strengths", "Сильные стороны"),
                     ("weaknesses", "Слабые стороны и пробелы"), ("customer_hypotheses", "Гипотезы о потребностях"),
                     ("differentiation", "Возможности отличиться"), ("practical_brief", "Практический бриф")],
        "creative": [("hypothesis", "Гипотеза"), ("trigger", "Триггер"), ("offer", "Оффер"),
                     ("headline", "Заголовок"), ("cta", "Призыв к действию"), ("image_brief", "Визуальная идея")],
        "mentor": [("principle", "Принцип"), ("evidence_explanation", "Основания решения"), ("alternative", "Сравнение с альтернативой"),
                   ("when_it_fails", "Когда гипотеза может не сработать"), ("validation_plan", "Как проверить")],
    }
    for key, label in fields[step]:
        value = result[key]
        sections.append(label + "\n" + ("\n".join("• " + x for x in value) if isinstance(value, list) else value))
    if step == "creative":
        sections.append("Сценарий Reels/Shorts\n" + "\n\n".join(
            f"{s['start_seconds']}–{s['end_seconds']} с\nВизуал: {s['visual']}\nРеплика: {s['narration']}\nУдержание внимания: {s['retention_hook']}"
            for s in result["scenes"]))
    if result["assumptions"]:
        sections.append("Допущения\n" + "\n".join("• " + x for x in result["assumptions"]))
    sections.append("Ограничения\n" + "\n".join("• " + x for x in artifact["limitations"]))
    if artifact["evidence"]:
        sections.append("Источники\n" + "\n".join(e["provenance"] for e in artifact["evidence"] if e["source_class"] == "EXTERNAL_PRIMARY"))
    sections.append(f"Проект: {artifact['run_id']}")
    return "\n\n".join(sections)


def delivery_parts(artifact):
    parts = [{"kind": "text", "text": chunk} for chunk in split_text(render_artifact(artifact))]
    step, run_id = artifact["step"], artifact["run_id"]
    if step in {"analysis", "creative"}:
        action = "creative" if step == "analysis" else "mentor"
        label = "Создать креативный пакет" if step == "analysis" else "Объяснить решение"
        parts[-1]["reply_markup"] = {"inline_keyboard": [[{"text": label, "callback_data": f"mvp:{run_id}:{action}"}]]}
    parts.extend({"kind": "image", "image_id": image["image_id"]} for image in artifact["images"])
    return parts
