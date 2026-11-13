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


def citation_role_allowed(output_name, role):
    """Keep demonstrations RTB-only; other source authority is checked separately."""
    return role != "demonstration" or output_name == "RTB"


def strategy_evidence(evidence):
    """Use the same source-role mapping for generation and verification choices."""
    return {item.record.evidence_id: {"role": STRATEGY_SOURCE_ROLES[item.input_key], "text": item.value}
            for item in evidence if item.input_key in STRATEGY_SOURCE_ROLES and isinstance(item.value, str)}


def strategy_selection_catalog(evidence):
    """Request-scoped opaque choices; only the server renders selected prose."""
    import hashlib
    import json

    sources = strategy_evidence(evidence)
    if not any(row["role"] == "product_identity" for row in sources.values()):
        return {}
    return {name: {"strategy_" + hashlib.sha256(json.dumps(choice, sort_keys=True, ensure_ascii=False).encode()).hexdigest(): choice
                   for choice in choices}
            for name, choices in build_strategy_choices(sources).items()}


POSITIONING_OUTPUT_PURPOSES: dict[str, str] = {
    "category": "Propose a meaningful product category. A clearly tentative category is valid when no alternative/category research was supplied.",
    "frame_of_reference": "Recommend concrete alternatives or a comparison frame. A hypothetical frame is valid without observed competitor or customer research.",
    "target": "Identify the intended audience using the supplied audience scope; do not add unsupported audience characteristics or product conditions.",
    "demand_context": "At WORKING depth, propose a clearly hypothetical situation in which the audience might consider the offer. Observed customer research is not required for an explicit HYPOTHESIS.",
    "JTBD_frame": "At WORKING depth, propose a clearly hypothetical task or desired change for the audience. An audience's hypothetical desired change is not a promise that the product delivers that outcome; observed customer research is not required.",
    "value_proposition": "Propose value grounded in authorized product terms. A feature-based value hypothesis is valid; its benefit must not become a guaranteed outcome.",
    "differentiation": "Propose a tentative distinction to test. Observed comparative superiority or competitor research is not required for an explicit hypothesis; never assert unsupported superiority.",
    "points_of_parity": "Propose expected category criteria as hypotheses to validate. Explicit hypothetical expectations are valid without observed category research.",
    "points_of_difference": "Propose specific distinctions in the offer or its communication as hypotheses. Do not invent competitor properties or imply the distinctions are already proven.",
    "RTB": "Present the complete actual cited owner substantiation or eligible demonstration, preserving all conditions. Owner assertions are not independent proof; demonstrations do not establish recurring product properties.",
    "positioning_statement": "Propose a coherent positioning combining the intended audience, product identity, category and grounded value angle; keep unvalidated value and comparative reasoning explicitly tentative.",
    "USP_directions": "Provide concrete, distinct messaging directions to test. Tentative directions need not establish observed uniqueness or competitor superiority.",
    "offer": "Preserve the complete authorized offer conditions, including fulfillment requirements and limits; do not invent commercial or operational terms.",
    "message_hierarchy": "Order actual product-specific messages and supporting conditions into a usable communication hierarchy; a list of generic section labels is insufficient.",
    "claim_risks": "Identify specific counterfactual checks and possible misreadings before publication. Warning against an unsupported feature or promise does not assert that it exists.",
    "validation_plan.": "Specify concrete questions or test targets for the proposed positioning and its uncertainties, without invented metrics, numeric thresholds or reported research findings.",
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
_PHOTOGRAPHY_IDENTITY = re.compile(r"Курс (?:мобильной )?фотографии(?: [^.!?\r\n]{1,120})?", re.IGNORECASE)
_CERAMICS_IDENTITY = re.compile(r"Мастер-класс (?:по )?керамик[еи](?: [^.!?\r\n]{1,120})?", re.IGNORECASE)


def source_fact_units(text: str) -> tuple[dict, ...]:
    """Plan known source propositions only after a complete closed-text match.

    Offsets are half-open Python Unicode codepoint ranges in the original source,
    for server use only. Sharing an anchor does not merge semantic propositions:
    materials and firing remain separate units even though their sentence is
    shared. This is a bounded source plan, not general semantic extraction. The
    caller must independently establish the source's authorized role.
    """
    if type(text) is not str:
        return ()

    def unit(identity, label, start, end):
        return {"unit_id": identity, "label": label, "start_char": start, "end_char": end}

    if text == _CERAMICS_TRUTH:
        first = "Материалы и обжиг включены."
        end = len(first)
        return (
            unit("materials_included", "Материалы включены", 0, end),
            unit("firing_included", "Обжиг включён", 0, end),
            unit("later_collection", "Получение после обжига в другой день", end + 1, len(text)),
        )
    if not _COURSE_TRUTH.fullmatch(text):
        return ()
    practical = "Участники выполняют практические задания"
    feedback = "и получают письменную обратную связь."
    equipment = "Для занятий не требуется профессиональное оборудование."
    # A permitted course title can itself contain the practical-task words.
    # The actual assertion is the final occurrence after the duration prefix.
    practical_start = text.rindex(practical)
    feedback_start = practical_start + len(practical) + 1
    units = []
    if practical_start:
        units.append(unit("duration", "Длительность курса", 0, practical_start - 1))
    units.extend((
        unit("practical_tasks", "Практические задания", practical_start, practical_start + len(practical)),
        unit("written_feedback", "Письменная обратная связь", feedback_start, feedback_start + len(feedback)),
    ))
    if text.endswith(equipment):
        units.append(unit("no_equipment", "Отсутствие требования к профессиональному оборудованию", len(text) - len(equipment), len(text)))
    return tuple(units)


def _profile_statements(profile: str, product: str, audience: str) -> dict[str, str]:
    """Propose distinct output roles; do not assert researched demand or superiority.

    These profiles are available only after complete identity and owner-truth
    checks below. Domain proposals stay tentative; operational statements use
    only the supplied terms. Offer and RTB are rendered by the exact-source wire.
    """
    if profile == "photography":
        return {
            "category": "Предлагаем категорию «обучение фотографии через практику с письменной обратной связью».",
            "frame_of_reference": "Предлагаем сравнивать курс фотографии с самостоятельным изучением приёмов съёмки; рамка выбора — сочетание практических заданий и письменной обратной связи.",
            "target": f"Предлагаем ориентировать сообщение курса фотографии на аудиторию «{audience}».",
            "demand_context": "Гипотеза ситуации спроса — человек пробует фотографировать и ищет ориентир для дальнейшей практики вместо накопления разрозненных советов.",
            "JTBD_frame": "Гипотеза задачи аудитории — понять, что пробовать менять в своих фотографиях после практики, опираясь на письменную обратную связь.",
            "value_proposition": "Предлагаем проверить ценность ориентира для дальнейшей фотопрактики через сочетание практических заданий и письменной обратной связи; важность этого акцента нужно выяснить у аудитории.",
            "differentiation": "Гипотеза отличия — сделать сочетание практических заданий и письменной обратной связи центральной темой сравнения курсов фотографии; заметность этого акцента ещё нужно проверить.",
            "points_of_parity": "Гипотеза базовых ожиданий от обучения фотографии — возможность практиковаться и понимать условия получения обратной связи; проверить эти критерии у аудитории.",
            "points_of_difference": "Предлагаем проверить различимость темы «практические задания и письменный отклик» в описании курса фотографии, не приписывая другим курсам отсутствие обратной связи.",
            "positioning_statement": f"Для аудитории «{audience}» предлагаем позиционирование «{product}» в категории «обучение фотографии через практику» с акцентом на сочетании практических заданий и письменной обратной связи как ориентире дальнейшей практики; ценность акцента требует проверки.",
            "USP_directions": "Направления сообщения для проверки: практика фотографии вместо накопления советов; письменная обратная связь как ориентир; осмысленный выбор следующего упражнения.",
            "message_hierarchy": "Главное сообщение для теста — курс фотографии с практическими заданиями и письменной обратной связью. Поддерживающий акцент — поиск направления дальнейшей практики. Условия участия — привести полный текст владельца. Следующий шаг — уточнить содержание заданий и порядок обратной связи.",
            "claim_risks": "Рекомендация перед публикацией — проверить, не подменяет ли сообщение практические задания домашними, а письменную обратную связь персональным разбором; уточнить темы курса и темп освоения у владельца.",
            "validation_plan.": "В беседах проверить, что аудитория понимает под письменной обратной связью и практическими заданиями, отличает их от домашних заданий и связывает предложенный акцент с задачей своей фотопрактики; спорные формулировки сверить с владельцем.",
        }
    return {
        "category": "Предлагаем категорию «знакомство с керамикой с заранее понятными условиями получения изделия».",
        "frame_of_reference": "Предлагаем сравнивать мастер-класс по керамике с самостоятельным знакомством с ремеслом и другими творческими занятиями; рамка выбора — ясность условий участия и получения изделия.",
        "target": f"Предлагаем ориентировать сообщение мастер-класса по керамике на аудиторию «{audience}».",
        "demand_context": "Гипотеза ситуации спроса — человек выбирает творческое занятие и хочет заранее понять, как вписать последующее получение изделия в свои планы.",
        "JTBD_frame": "Гипотеза задачи аудитории — познакомиться с керамикой и заранее согласовать ожидания по получению изделия после обжига.",
        "value_proposition": "Предлагаем проверить ценность понятного планирования участия: материалы и обжиг включены, а получение изделия относится к другому дню; акцент сообщения — понимать путь участия до записи.",
        "differentiation": "Гипотеза отличия сообщения — сделать последующее получение изделия заметной частью выбора мастер-класса по керамике; сравнение с другими предложениями ещё предстоит проверить.",
        "points_of_parity": "Гипотеза базовых ожиданий от творческого мастер-класса — понятные условия материалов, обжига и получения изделия; проверить важность этих критериев у аудитории.",
        "points_of_difference": "Предлагаем проверить, выделяет ли описание мастер-класса по керамике открытое обозначение получения изделия в другой день, не утверждая, что остальные скрывают свои условия.",
        "positioning_statement": f"Для аудитории «{audience}» предлагаем позиционирование «{product}» в категории «знакомство с керамикой» с акцентом на ясных условиях материалов, обжига и получения изделия в другой день; ценность такого акцента требует проверки.",
        "USP_directions": "Направления сообщения для проверки: знакомство с керамикой; включённые материалы и обжиг; заранее понятное получение изделия в другой день.",
        "message_hierarchy": "Главное сообщение для теста — мастер-класс по керамике с ясными условиями получения изделия. Поддержка — материалы и обжиг включены. Условие — забрать изделие после обжига в другой день. Следующий шаг — уточнить порядок получения до записи.",
        "claim_risks": "Рекомендация перед публикацией — проверить, не создаёт ли сообщение ожидание выдачи изделия в день занятия и не приписывает ли конкретную технику работы с глиной или помощь мастера; сохранить условие другого дня и уточнить содержание занятия у владельца.",
        "validation_plan.": "В беседах проверить понимание получения изделия в другой день, влияние этого условия на выбор занятия и оставшиеся вопросы о работе с глиной; порядок получения и содержание занятия сверить с владельцем.",
    }


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
    identity_dependencies = ()

    def add(name, text, identities=()):
        # Existing executor numeric provenance rules still apply. Avoid creating
        # a known-invalid mixed strategic sentence from numbered product names.
        if len(text) > 4000 or any(char.isdigit() for char in text):
            return
        item = {"text": text, "required_source_ids": sorted(set((*identity_dependencies, *identities)))}
        if item not in choices[name]:
            choices[name].append(item)

    def single(role):
        rows = [(identity, row["text"]) for identity, row in sorted(evidence.items())
                if row.get("role") == role and type(row.get("text")) is str and row["text"].strip()]
        return rows[0] if len(rows) == 1 else None

    product, audience = single("product_identity"), single("audience")
    if product:
        identity_dependencies = (product[0],)
    truth = single("product_truth")
    profile = None
    if product and audience and truth:
        if _PHOTOGRAPHY_IDENTITY.fullmatch(product[1]) and _COURSE_TRUTH.fullmatch(truth[1]):
            profile = "photography"
        elif _CERAMICS_IDENTITY.fullmatch(product[1]) and truth[1] == _CERAMICS_TRUTH:
            profile = "ceramics"
    if profile:
        required = (product[0], audience[0], truth[0])
        for name, text in _profile_statements(profile, product[1], audience[1]).items():
            add(name, text, required)
        return {name: tuple(options) for name, options in choices.items()}
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
