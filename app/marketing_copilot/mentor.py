"""Grounded explanations of accepted cases, with no new execution engine/provider.

The companion MarketingRun groups durable explanations/questions/feedback. The
source graph's strict node-artifact namespace and lifecycle remain untouched.
"""
import hashlib
import json

from pydantic import ValidationError
from sqlalchemy import select

from app.models import MarketingArtifact, MarketingRun, User
from app.module_execution.executors.claim_support import assertion_support
from app.module_execution.executors.common import plain
from app.module_execution.executors.intelligence_schemas import StrategyOutput, ExperimentsOutput
from app.module_registry import ModuleId
from app.orchestration_runtime.contracts import WORKFLOW_TYPE
from app.orchestration_runtime.errors import RuntimeContractError
from .api_errors import CopilotAPIError, ProviderUnavailable
from .mentor_contracts import MentorExplanation, MentorSection, MentorAnswer, SavedFeedback
from .presentation import sources

COMPANION_TYPE = "case_mentor.v1"
EXPLANATION_KEY = "explanation.v1"
KIND_LABELS = {"FACT": "Утверждение источника", "OBSERVATION": "Наблюдение", "INFERENCE": "Вывод",
    "HYPOTHESIS": "Гипотеза", "ASSUMPTION": "Допущение", "FORECAST": "Прогноз", "RECOMMENDATION": "Рекомендация"}
INPUT_LABELS = {"business_goal": "Бизнес-цель", "product": "Продукт", "target_or_target_hypothesis": "Аудитория",
    "customer_job_or_need": "Задача клиента", "relevant_alternative": "Альтернатива клиента",
    "product_truth": "Сведения о продукте", "existing_proof": "Предоставленные подтверждения",
    "geography": "География", "economics": "Экономика", "message": "Сообщение"}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def paragraphs(values):
    # Preserve all source text while respecting the public text field limit.
    return [value[i:i + 4000] for value in values if value for i in range(0, len(value), 4000)]


def explanation(run_id, plan, accepted):
    node = next((n for n in plan.nodes if n.module_id is ModuleId.VIRTUAL_CMO and n.node_id in accepted), None)
    if node is None:
        raise CopilotAPIError(409, "execution_invalid")
    result = accepted[node.node_id]
    wire = StrategyOutput.model_validate(plain(result.payload))
    outputs = {s.output_name.rstrip("."): s for s in wire.outputs}
    packet = node.context_packet
    inputs = []
    goal = []
    for fact in (*packet.relevant_project_context, *packet.known_facts):
        if fact.label not in INPUT_LABELS or fact.value is None:
            continue
        value = plain(fact.value)
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        inputs.append(f"{INPUT_LABELS[fact.label]} (предоставленный контекст, не независимая проверка): {text}")
        if fact.label == "business_goal":
            goal.append(text)
    claims = {claim.claim_id: claim for item in accepted.values() for claim in item.normalized_result.claims}
    rationale = []
    shown_support = set()
    for statement in wire.outputs:
        if statement.output_name.rstrip(".") in {"trade_offs", "risks", "decision_triggers"}:
            continue
        rationale.extend([f"{KIND_LABELS[statement.kind]}; уверенность {statement.confidence}: {statement.text}", *statement.items])
        # These are persisted lineage links, not reconstructed private reasoning.
        cited = set()
        pending = list(statement.parent_claim_ids)
        while pending:
            ref = pending.pop(0)
            if ref in cited:
                continue
            cited.add(ref)
            parent = claims.get(ref)
            if parent is not None:
                if ref not in shown_support:
                    rationale.extend(f"Сохранённое основание ({KIND_LABELS[parent.claim_type.value]}; {parent.confidence.value}): {text}"
                        for text in assertion_support(parent.value))
                    shown_support.add(ref)
                pending.extend(parent.parent_claim_ids)
        if not cited:
            rationale.append("Для этого решения не сохранена связь с предыдущими утверждениями; причину выбора нельзя восстановить.")
    def selected(*keys):
        return [text for key in keys if key in outputs for text in (outputs[key].text, *outputs[key].items)]
    verification = []
    for item in accepted.values():
        if item.module_id is ModuleId.EXPERIMENTS:
            for experiment in ExperimentsOutput.model_validate(plain(item.payload)).experiments:
                verification.extend([f"Проверяемая гипотеза: {experiment.hypothesis}", f"Изменение: {experiment.intervention}",
                    f"Метрика: {experiment.target_metric}", f"Ожидаемый сигнал (не фактический результат): {experiment.expected_signal}",
                    f"Условие отказа: {experiment.failure_condition}",
                    *[f"Нужные данные: {v}" for v in experiment.minimum_required_inputs],
                    *[f"Ресурсное ограничение: {v}" for v in experiment.time_resource_constraints]])
    if not verification:
        verification = ["Отдельный план эксперимента не сохранён. Неизвестны необходимый объём выборки и фактическая эффективность.", *selected("decision_triggers")]
    limitations = [*wire.limitations, *wire.assumptions, *packet.assumptions, *packet.constraints, *packet.open_questions,
        *[item.description for item in result.normalized_result.limitations if item.description], *selected("risks"),
        "Рекомендации и прогнозы AI не являются фактическими результатами. Связь с источником не доказывает причинность и не гарантирует продажи.",
        "Разбор показывает сохранённые решения и их основания; недоступная история рассуждений модели не восстанавливается."]
    if not any(f.label == "economics" and f.value for f in (*packet.relevant_project_context, *packet.known_facts)):
        limitations.append("Отдельное экономическое обоснование не сохранено: доступность каналов и окупаемость не подтверждены. Сохранённые ресурсные ограничения приведены выше.")
    source_values = []
    for item in accepted.values():
        for source in sources(item):
            value = "Источник: " + source.label + (" — " + source.url if source.url else "")
            if value not in source_values:
                source_values.append(value)
    sections = [
        ("goal", "Цель решения", goal or ["Явная бизнес-цель не сохранена; не следует подменять её предполагаемой целью."]),
        ("inputs", "Исходные данные", [*inputs, *source_values] or ["Исходные данные не сохранены."]),
        ("principle", "Маркетинговый принцип", ["Связывайте бизнес-цель с главным ограничением роста, приоритетом ресурсов и проверяемой гипотезой. Ниже приведены сохранённые формулировки этого кейса, а не новое решение.", *selected("strategic_diagnosis", "main_growth_constraint")]),
        ("rationale", "Основания выбора", rationale or ["Основания решений не сохранены."]),
        ("alternatives", "Альтернативы и компромиссы", [*selected("trade_offs", "resource_priorities"), "Это сохранённые компромиссы; превосходство над нерассмотренным каналом или вариантом бюджета не доказано."]),
        ("limitations", "Ограничения и допущения", list(dict.fromkeys(limitations))),
        ("verification", "Практическая проверка", verification),
        ("takeaway", "Принцип для следующего кейса", ["Прежде чем масштабировать рекомендацию, проверьте указанную гипотезу на своей аудитории и сопоставьте метрику с бизнес-целью. Если изменились аудитория, бюджет или условия отказа, пересмотрите решение, сохранив исходный кейс.", *selected("decision_triggers")]),
    ]
    return MentorExplanation(run_id=run_id, sections=[MentorSection(key=key, title=title, paragraphs=paragraphs(values)) for key, title, values in sections])


class CaseMentorService:
    def __init__(self, sessions, graph):
        self.sessions, self.graph = sessions, graph

    async def _source(self, session, actor, run_id, *, lock=False):
        query = select(MarketingRun).join(User).where(MarketingRun.run_id == run_id,
            MarketingRun.workflow_type == WORKFLOW_TYPE, User.telegram_id == actor)
        if lock:
            query = query.with_for_update(of=MarketingRun)
        run = await session.scalar(query)
        if run is None:
            raise CopilotAPIError(404, "not_found")
        return run

    @staticmethod
    def companion_id(run_id):
        return digest(COMPANION_TYPE + ":" + run_id)

    async def _artifact(self, session, run_id, key):
        return await session.scalar(select(MarketingArtifact).where(
            MarketingArtifact.run_id == self.companion_id(run_id), MarketingArtifact.artifact_key == key))

    async def _create(self, session, source, key, payload, *, request=None):
        companion_id = self.companion_id(source.run_id)
        companion = await session.get(MarketingRun, companion_id)
        if companion is None:
            session.add(MarketingRun(run_id=companion_id, user_id=source.user_id,
                workflow_type=COMPANION_TYPE, status="completed", input_json={"source_run_id": source.run_id}, state_json={}))
            await session.flush()
        elif (companion.user_id != source.user_id or companion.workflow_type != COMPANION_TYPE
                or companion.input_json != {"source_run_id": source.run_id}):
            raise CopilotAPIError(409, "request_conflict")
        session.add(MarketingArtifact(run_id=companion_id, artifact_key=key,
            artifact_type=payload.schema_version, step="mentor", payload_json={"value": payload.model_dump(mode="json"), "request": request}))

    async def _explain_locked(self, session, source):
        saved = await self._artifact(session, source.run_id, EXPLANATION_KEY)
        if saved:
            return MentorExplanation.model_validate(saved.payload_json["value"])
        if source.status not in {"completed", "completed_with_limitations"}:
            raise CopilotAPIError(409, "execution_invalid")
        revision, plan = await self.graph._plan(session, source.run_id)
        _, accepted = await self.graph._graph_state(session, source.run_id, revision, plan)
        value = explanation(source.run_id, plan, accepted)
        await self._create(session, source, EXPLANATION_KEY, value)
        return value

    async def explain(self, actor, run_id):
        try:
            async with self.sessions() as session, session.begin():
                source = await self._source(session, actor, run_id, lock=True)
                return await self._explain_locked(session, source)
        except (ValidationError, RuntimeContractError) as exc:
            raise ProviderUnavailable() from exc

    async def get(self, actor, run_id):
        async with self.sessions() as session:
            await self._source(session, actor, run_id)
            saved = await self._artifact(session, run_id, EXPLANATION_KEY)
            if saved is None:
                raise CopilotAPIError(404, "not_found")
            return MentorExplanation.model_validate(saved.payload_json["value"])

    async def question(self, actor, run_id, request):
        async with self.sessions() as session, session.begin():
            source = await self._source(session, actor, run_id, lock=True)
            key = "question:" + digest(request.request_key)
            saved = await self._artifact(session, run_id, key)
            raw = request.model_dump(mode="json")
            if saved:
                if saved.payload_json["request"] != raw:
                    raise CopilotAPIError(409, "request_conflict")
                return MentorAnswer.model_validate(saved.payload_json["value"])
            case = await self._explain_locked(session, source)
            question = request.question.casefold()
            if any(word in question for word in ("альтернатив", "почему не", "контекстн", "канал", "alternative", "channel")):
                focus, keys = "alternative", ("goal", "rationale", "alternatives", "limitations")
            elif any(word in question for word in ("провер", "метрик", "эксперимент", "test", "metric", "experiment")):
                focus, keys = "verification", ("goal", "verification", "limitations")
            elif any(word in question for word in ("бюджет", "аудитори", "ресурс", "budget", "audience", "resource")):
                focus, keys = "resources", ("inputs", "alternatives", "limitations", "verification")
            elif any(word in question for word in ("основан", "факт", "данны", "источник", "evidence", "fact", "source")):
                focus, keys = "evidence", ("inputs", "rationale", "limitations")
            else:
                focus, keys = "overview", ("goal", "principle", "rationale", "verification", "takeaway")
            values = ["Разбор использует тот же сохранённый кейс. Новая стратегия и расчёт сценария не генерируются."]
            if focus in {"alternative", "resources"}:
                values.append("Если запрошенный канал, бюджет или аудитория не сравнивались в исходной стратегии, данных для вывода об их превосходстве нет. Ниже — сохранённые основания и условия проверки, а не новая сравнительная оценка.")
            values.extend(p for section in case.sections if section.key in keys for p in [section.title, *section.paragraphs])
            feedback = (await session.scalars(select(MarketingArtifact).where(
                MarketingArtifact.run_id == self.companion_id(run_id), MarketingArtifact.artifact_type == "case_feedback.v1")
                .order_by(MarketingArtifact.created_at.desc()).limit(10))).all()
            for row in reversed(feedback):
                report = SavedFeedback.model_validate(row.payload_json["value"])
                values.extend(["Обратная связь пользователя (не независимо проверено; не исходный прогноз): " + report.outcome,
                    report.notes, report.metrics])
            answer = MentorAnswer(run_id=run_id, question=request.question, focus=focus, paragraphs=paragraphs(values))
            await self._create(session, source, key, answer, request=raw)
            return answer

    async def feedback(self, actor, run_id, request):
        async with self.sessions() as session, session.begin():
            source = await self._source(session, actor, run_id, lock=True)
            await self._explain_locked(session, source)
            key, raw = "feedback:" + digest(request.request_key), request.model_dump(mode="json")
            saved = await self._artifact(session, run_id, key)
            if saved:
                if saved.payload_json["request"] != raw:
                    raise CopilotAPIError(409, "request_conflict")
                return SavedFeedback.model_validate(saved.payload_json["value"])
            value = SavedFeedback(run_id=run_id, **request.model_dump(exclude={"request_key"}))
            await self._create(session, source, key, value, request=raw)
            return value
