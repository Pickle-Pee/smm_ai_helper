"""Closed prospective language permitted without factual source quotations.

Membership establishes only that wording asks a marketing research question or
proposes a test. It does not establish product properties, audience preferences,
competitor behavior, or the usefulness of a positioning strategy. Generation and
semantic acceptance must still assess relevance and distinctness separately.
"""

import re


STRATEGY_SOURCE_ROLES = {
    "product": "product_identity",
    "target_or_target_hypothesis": "audience",
    "product_truth": "product_truth",
    "existing_proof": "demonstration",
}


STRATEGY_OPTIONS: dict[str, tuple[str, ...]] = {
    "category": (
        "Проверить, как аудитория определяет категорию при выборе.",
        "Исследовать, какие названия категории понятны аудитории.",
        "Test which category descriptions make the choice easier to understand.",
    ),
    "frame_of_reference": (
        "Исследовать, с какими альтернативами аудитория сравнивает предложение.",
        "Проверить, какой контекст сравнения помогает объяснить предложение.",
        "Research which alternatives the audience considers when making a choice.",
    ),
    "target": (
        "Проверить интерес среди людей, которые рассматривают знакомство с новой практикой.",
        "Исследовать, кому важно понять следующий шаг перед выбором.",
        "Test which prospective audience groups express interest in learning more.",
    ),
    "demand_context": (
        "Проверить, в каких ситуациях возникает интерес к предложению.",
        "Исследовать, какие сомнения мешают аудитории сделать выбор.",
        "Проверить интерес к практике фотографии.",
        "Research which situations prompt the audience to consider the offer.",
    ),
    "JTBD_frame": (
        "Исследовать, какую задачу аудитория хочет решить при выборе.",
        "Проверить, какой следующий шаг аудитория считает полезным.",
        "Test whether beginners value knowing what to practice next.",
    ),
    "value_proposition": (
        "Тестировать акцент на применении навыков.",
        "Проверить, помогает ли ясность следующего шага объяснить ценность предложения.",
        "Гипотеза: аудитории может быть важна ясность следующего шага.",
        "Test whether clarity about the next step increases interest in learning more.",
    ),
    "differentiation": (
        "Проверить, какие критерии выбора аудитория считает значимыми при сравнении.",
        "Исследовать, какой акцент помогает различать альтернативы без обещания превосходства.",
        "Test which comparison criteria matter to the audience without claiming superiority.",
    ),
    "points_of_parity": (
        "Исследовать, какие базовые ожидания аудитория предъявляет к категории.",
        "Проверить, какую информацию аудитория ожидает увидеть перед сравнением.",
        "Research which basic expectations the audience has when comparing alternatives.",
    ),
    "points_of_difference": (
        "Тестировать разные акценты сообщения и сравнить интерес аудитории.",
        "Проверить, какие различия аудитория замечает в описаниях альтернатив.",
        "Test which messaging angles the audience distinguishes when comparing alternatives.",
    ),
    "RTB": (
        "Уточнить у владельца, какие подтверждения можно использовать в сообщении.",
        "Проверить, какие подтверждения аудитория считает достаточными перед выбором.",
        "Ask which substantiation the audience needs before considering the offer.",
    ),
    "positioning_statement": (
        "Тестировать позиционирование через ясность выбора и следующего шага.",
        "Проверить позиционирование через интерес к знакомству с практикой.",
        "Test a positioning angle centered on clarity of choice and the next step.",
    ),
    "USP_directions": (
        "Сравнить интерес к сообщениям о выборе, практике и следующем шаге.",
        "Проверить разные направления сообщения до выбора основного акцента.",
        "Compare interest in messaging about choice, practice, and the next step.",
    ),
    "offer": (
        "Проверить, какая информация об условиях нужна аудитории перед решением.",
        "Уточнить условия предложения у владельца перед подготовкой публичного сообщения.",
        "Ask which offer conditions the audience needs clarified before deciding.",
    ),
    "message_hierarchy": (
        "Тестировать порядок сообщения: интерес, условия, подтверждение и следующий шаг.",
        "Сравнить, с какого вопроса аудитории полезнее начинать сообщение.",
        "Test a message sequence covering interest, conditions, substantiation, and the next step.",
    ),
    "claim_risks": (
        "Уточнить, что именно получает участник после курса.",
        "Проверить фактические основания каждого обещания перед публикацией.",
        "Review the factual basis of each proposed promise before publication.",
    ),
    "validation_plan.": (
        "Собрать вопросы аудитории и проверить понимание сообщения до публикации.",
        "Сравнить отклик на разные акценты и уточнить причины выбора.",
        "Ask participants whether the timing meets their needs.",
    ),
}

_SAFE_STATEMENTS = frozenset(text for options in STRATEGY_OPTIONS.values() for text in options)

# Closed candidate-feature questions do not say that a current product contains
# the candidate feature. Restrict the whole utterance, including its object; a
# factual subordinate clause cannot be appended after an otherwise safe prefix.
_PROSPECTIVE_QUESTION = re.compile(
    r"(?:"
    r"(?:Test|Ask|Check|Research|Validate)\s+(?:whether|if)\s+"
    r"(?:the\s+)?(?:audience|participants|learners|beginners|customers)\s+"
    r"(?:need|want|value|prefer|would\s+value|would\s+prefer)\s+"
    r"(?:an?\s+|the\s+)?"
    r"(?:online\s+format|homework|personal\s+feedback|written\s+feedback|teacher\s+support)"
    r"|(?:Проверить|Выяснить|Исследовать|Спросить)[,:]?\s+"
    r"(?:нуж(?:ен|на|но|ны)\s+ли|важ(?:ен|на|но|ны)\s+ли)\s+"
    r"(?:аудитории|участникам|ученикам|новичкам|клиентам)\s+"
    r"(?:онлайн[-\s]формат|домашние\s+задания|персональная\s+обратная\s+связь"
    r"|письменная\s+обратная\s+связь|помощь\s+преподавателя)"
    r")[.?!]?",
    re.IGNORECASE,
)


def safe_strategy_statement(text: str) -> bool:
    """Recognize closed prospective wording, trimming outer whitespace only.

    Arbitrary paraphrases fail closed. No Unicode normalization, substring
    matching, model label or absence of a known bad word grants approval.
    """
    if type(text) is not str:
        return False
    statement = text.strip()
    return statement in _SAFE_STATEMENTS or _PROSPECTIVE_QUESTION.fullmatch(statement) is not None


_COURSE_TRUTH = re.compile(
    r"(?:Курс [^.!?\n]{1,120} длится 6 недель\. )?"
    r"Участники выполняют практические задания и получают письменную обратную связь\."
    r"(?: Для занятий не требуется профессиональное оборудование\.)?"
)
_CERAMICS_TRUTH = (
    "Материалы и обжиг включены. Участники забирают изделия после обжига в другой день."
)


def build_strategy_choices(evidence: dict[str, dict]) -> dict[str, tuple[dict, ...]]:
    """Render bounded, request-scoped positioning proposals from trusted slots.

    Identity/audience slots quote complete authorized source text; they do not
    create product proof. Feature-bearing angles require a full, closed owner
    truth pattern and carry that entire source's identity. The caller must bind
    these choices to its immutable draft and enforce all required citations.
    Unknown source language enables only prospective generic strategic angles.
    Offer and RTB remain exact-source outputs and have no generated alternatives.
    """
    choices: dict[str, list[dict]] = {name: [] for name in STRATEGY_OPTIONS}

    def add(name, text, identities=()):
        # Existing executor numeric provenance rules still apply. Avoid creating
        # a known-invalid mixed strategic sentence from numbered product names.
        if len(text) > 4000 or any(char.isdigit() for char in text):
            return
        item = {"text": text, "required_source_ids": sorted(set(identities))}
        if item not in choices[name]:
            choices[name].append(item)

    def single(role):
        rows = [(identity, row["text"]) for identity, row in sorted(evidence.items())
                if row.get("role") == role and type(row.get("text")) is str and row["text"].strip()]
        return rows[0] if len(rows) == 1 else None

    product, audience = single("product_identity"), single("audience")
    # A source-specific angle is deliberately gated by the WHOLE owner text.
    # A quotation, hypothetical example or conditional prefix cannot enable it.
    angles = []
    for identity, row in sorted(evidence.items()):
        if row.get("role") != "product_truth" or type(row.get("text")) is not str:
            continue
        if _COURSE_TRUTH.fullmatch(row["text"]):
            angles.append(("письменная обратная связь как ориентир для практики", identity))
        elif row["text"] == _CERAMICS_TRUTH:
            angles.append(("прозрачность условий получения изделия", identity))
    if not angles:
        angles.append(("ясность выбора и следующего шага", None))

    add("category", "Предлагаем проверить категорию «освоение новой практики».")
    add("frame_of_reference", "Предлагаем сравнивать подходы к знакомству с новой практикой.")
    add("JTBD_frame", "Гипотеза задачи аудитории — понять, интересно ли продолжать знакомство с новой практикой.")
    add("demand_context", "Гипотеза ситуации выбора — поиск следующего шага при знакомстве с новой практикой.")
    add("points_of_parity", "Предлагаемые критерии сравнения — понятность условий и следующего шага.")
    add("USP_directions", "Предлагаемые направления сообщения — ясность выбора и интерес к практике.")
    add("message_hierarchy", "Рекомендуемый порядок сообщения — интерес, полные условия, подтверждение и следующий шаг.")
    add("claim_risks", "Рекомендуем отделять подтверждённые условия от гипотез о ценности перед публикацией.")
    add("validation_plan.", "Проверить понимание предложенной категории, ценности и причин выбора в беседах с аудиторией.")
    if audience:
        identity, text = audience
        add("target", f"Предлагаем проверить позиционирование для аудитории «{text}».", (identity,))
        add("JTBD_frame", f"Для аудитории «{text}» предлагаем проверить задачу — выбрать следующий шаг в знакомстве с практикой.", (identity,))
    else:
        add("target", "Предлагаем проверить аудиторию людей, выбирающих знакомство с новой практикой.")

    for angle, truth_id in angles:
        required = (truth_id,) if truth_id else ()
        add("value_proposition", f"Предлагаемый акцент ценности для проверки — {angle}.", required)
        add("differentiation", f"Гипотеза отличия для проверки — акцент на теме «{angle}», без утверждения превосходства.", required)
        add("points_of_difference", f"Предлагаем проверить, помогает ли акцент «{angle}» различать альтернативы при выборе.", required)
        if product:
            identity, text = product
            add("value_proposition", f"Для «{text}» предлагаем проверить акцент ценности «{angle}».", (*required, identity))
        if product and audience:
            product_id, product_text = product
            audience_id, audience_text = audience
            add("positioning_statement",
                f"Для аудитории «{audience_text}» предлагаем проверить позиционирование «{product_text}» "
                f"в категории «освоение новой практики» с акцентом на теме «{angle}».",
                (*required, product_id, audience_id))
        else:
            add("positioning_statement", f"Рекомендуемая территория позиционирования для проверки — {angle}.", required)
    return {name: tuple(options) for name, options in choices.items()}
