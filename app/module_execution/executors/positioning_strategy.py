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
        "Проверить интерес среди людей, которые уже решают задачу, на которую направлено предложение.",
        "Исследовать, кому важно понять следующий шаг перед выбором.",
        "Test which prospective audience groups express interest in the offer.",
    ),
    "demand_context": (
        "Проверить, в каких ситуациях возникает интерес к предложению.",
        "Исследовать, какие сомнения мешают аудитории сделать выбор.",
        "Проверить, какие ситуации заставляют аудиторию искать альтернативу текущему выбору.",
        "Research which situations prompt the audience to consider the offer.",
    ),
    "JTBD_frame": (
        "Исследовать, какую задачу аудитория хочет решить при выборе.",
        "Проверить, какой следующий шаг аудитория считает полезным.",
        "Test which task the audience wants to complete when choosing.",
    ),
    "value_proposition": (
        "Тестировать акцент на полноте условий предложения.",
        "Проверить, помогает ли ясность следующего шага объяснить ценность предложения.",
        "Гипотеза: аудитории может быть важна ясность следующего шага.",
        "Test whether clarity about the next step increases interest in the offer.",
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
        "Проверить позиционирование через задачу, которую аудитория решает при выборе.",
        "Test a positioning angle centered on clarity of choice and the next step.",
    ),
    "USP_directions": (
        "Сравнить интерес к сообщениям о задаче, условиях и следующем шаге.",
        "Проверить разные направления сообщения до выбора основного акцента.",
        "Compare interest in messaging about the task, conditions, and the next step.",
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
        "Уточнить у владельца, что именно входит в предложение.",
        "Проверить фактические основания каждого обещания перед публикацией.",
        "Review the factual basis of each proposed promise before publication.",
    ),
    "validation_plan.": (
        "Собрать вопросы аудитории и проверить понимание сообщения до публикации.",
        "Сравнить отклик на разные акценты и уточнить причины выбора.",
        "Ask the audience whether the stated conditions meet their needs.",
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


def _quoted(text: str) -> str:
    """Quote complete owner text; only a trailing sentence period is display punctuation."""
    return "«" + text.strip().removesuffix(".").rstrip() + "»"


def build_strategy_choices(evidence: dict[str, dict]) -> dict[str, tuple[dict, ...]]:
    """Render bounded, request-scoped, domain-neutral positioning proposals.

    Identity/audience slots quote complete authorized source text; they do not
    create product proof. No proposal depends on recognizing a product domain or
    a particular owner wording: the same templates serve a course, a bakery or a
    B2B service. Owner terms are referenced as a whole, never paraphrased or
    fragmented; their exact text stays in the SOURCE offer and RTB outputs. The
    caller must bind these choices to its immutable draft and enforce all
    required citations. Offer and RTB have no generated alternatives.
    Product-specific market hypotheses are a separate, independently verified
    design (docs/development/positioning-domain-generalization-design.md).
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

    product, audience, truth = single("product_identity"), single("audience"), single("product_truth")
    if product:
        identity_dependencies = (product[0],)
    terms = (truth[0],) if truth else ()

    add("category", "Предлагаем рабочую категорию — описание предложения словами владельца; "
        "проверить, теми ли словами аудитория ищет такие предложения.")
    add("frame_of_reference", "Предлагаем рамку сравнения — способы, которыми аудитория решает ту же задачу сейчас, "
        "включая вариант ничего не менять; состав альтернатив проверить в беседах.")
    add("demand_context", "Гипотеза ситуации спроса — аудитория начинает искать предложение, когда текущий способ "
        "решения задачи перестаёт её устраивать; проверить, какие ситуации к этому приводят.")
    add("JTBD_frame", "Гипотеза задачи аудитории — решить свою задачу с меньшими усилиями и неопределённостью, "
        "чем при текущем способе; конкретную формулировку задачи проверить в интервью.")
    add("points_of_parity", "Гипотеза базовых ожиданий от альтернатив — понятные условия, предсказуемый следующий шаг "
        "и отсутствие скрытых требований; проверить эти критерии у аудитории.")
    add("USP_directions", "Направления сообщения для проверки: задача аудитории её словами; полные условия владельца "
        "без сокращений; понятный следующий шаг.")
    add("message_hierarchy", "Рекомендуемый порядок сообщения — задача аудитории, полные условия владельца, "
        "подтверждение и следующий шаг.")
    add("claim_risks", "Рекомендуем перед публикацией сверить каждое обещание с полными условиями владельца "
        "и не сокращать их оговорки.")
    add("validation_plan.", "Проверить в беседах с аудиторией понимание категории, рамки сравнения и полных условий, "
        "а также причины выбора или отказа.")
    if product:
        add("category", f"Предлагаем проверить рабочую категорию {_quoted(product[1])} — так владелец описывает "
            "предложение; выяснить, теми ли словами аудитория ищет такие предложения.")
    if audience:
        audience_id, audience_text = audience
        add("target", f"Предлагаем ориентировать позиционирование на аудиторию {_quoted(audience_text)}.", (audience_id,))
        add("JTBD_frame", f"Гипотеза задачи аудитории {_quoted(audience_text)} — решить свою задачу с меньшими "
            "усилиями и неопределённостью, чем при текущем способе; формулировку задачи проверить в интервью.",
            (audience_id,))
    else:
        add("target", "Предлагаем проверить, какие группы аудитории уже решают задачу, на которую направлено предложение.")

    # Feature-free angles reference the owner's terms as a whole; they never
    # restate, strengthen or select a fragment of those terms.
    angle = "полное изложение условий владельца без сокращений" if truth else "ясность выбора и следующего шага"
    add("value_proposition", f"Предлагаемый акцент ценности для проверки — {angle}; результат не обещается.", terms)
    add("differentiation", f"Гипотеза отличия для проверки — акцент на теме «{angle}», "
        "без утверждения превосходства и без приписывания альтернативам скрытых условий.", terms)
    add("points_of_difference", f"Предлагаем проверить, помогает ли акцент «{angle}» различать альтернативы при выборе.",
        terms)
    if product:
        add("value_proposition", f"Для {_quoted(product[1])} предлагаем проверить акцент ценности «{angle}».", terms)
    if product and audience:
        add("positioning_statement",
            f"Для аудитории {_quoted(audience[1])} предлагаем проверить позиционирование {_quoted(product[1])} "
            f"с акцентом на теме «{angle}»; ценность акцента требует проверки.", (*terms, audience[0]))
    else:
        add("positioning_statement", f"Рекомендуемая территория позиционирования для проверки — {angle}.", terms)
    return {name: tuple(options) for name, options in choices.items()}
