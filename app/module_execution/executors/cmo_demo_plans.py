"""Closed CMO demo-material plans; free CMO prose cannot describe demo materials.

Telegram/live acceptance repeatedly failed on new free-text paraphrases of a
prospective demo plan («Сделать…», «создание демонстраций…», «демонстрационный
фрагмент…»). Instead of growing the downstream creation grammar, the provider
schema now forbids demo vocabulary in free CMO prose and offers a small closed
set of generic, domain-independent plan sentences. They name no demo contents,
claim nothing about an existing demo and pass the unchanged downstream checks
without an exemption. Current demo facts still use exact SOURCE tokens.
"""
from copy import deepcopy

from app.module_execution.errors import ModuleExecutionContractError
from .qualitative_generation import (
    GENERATION_COUNT_WORDS, PROSE_SEPARATOR, QUALITATIVE_GENERATION_PATTERN, allowed_word_pattern, generation_pattern,
)

# Whole forbidden words and forbidden stems (every word starting with them).
DEMO_WORDS = frozenset(("демо", "demo", "demos", "proof", "proofs"))
DEMO_STEMS = ("демонс", "demonst")
# Free CMO prose (v15): no demo vocabulary and no "_" (schema keys such as
# audience_understanding_ru).
# v16: equipment conditions are owner terms. Free paraphrases repeatedly lost
# their qualifiers or stated a fragment of a ";"-joined leaf, so the vocabulary
# aligned with positioning_assurance.equipment_absence_spans is closed as well.
EQUIPMENT_WORDS = frozenset(("gear",))
EQUIPMENT_STEMS = ("оборуд", "equipm")
# v17: a bare kind label (RECOMMENDATION / HYPOTHESIS) in place of content is
# excluded through the same word trie. The v15 two-word structure was rejected by
# the provider (empty incomplete response), so the accepted structure is kept.
LABEL_STEMS = ("recomm", "hypoth")
# Changing this pattern requires a new provider capability probe: structure, not
# size, decided acceptance. The exact value below was accepted on 15.11.2026.
DEMO_FREE_PATTERN = generation_pattern(
    allowed_word_pattern(GENERATION_COUNT_WORDS | DEMO_WORDS | EQUIPMENT_WORDS,
                         DEMO_STEMS + EQUIPMENT_STEMS + LABEL_STEMS),
    separator=PROSE_SEPARATOR)

DEMO_PLAN_NOTES = (
    "Подготовить новый демонстрационный материал строго по полному подтверждённому описанию владельца, "
    "без дополнительных обещаний, и согласовать его с владельцем до использования.",
    "Проверить в беседах, как аудитория понимает новый демонстрационный материал, "
    "не считая её реакцию доказательством результата.",
    "Использовать новый демонстрационный материал в коммуникации только после согласования с владельцем "
    "и проверки понимания аудиторией.",
    "Prepare a new demonstration material strictly from the complete confirmed owner description, "
    "without additional promises, and agree it with the owner before use.",
    "Check in interviews how the audience understands the new demonstration material, "
    "without treating its reaction as evidence of results.",
    "Use the new demonstration material in communication only after owner approval "
    "and a check of audience understanding.",
)
# Closed, domain-independent equipment plans: they state no requirement and no
# absence of one, and send the reader to the complete owner terms.
EQUIPMENT_PLAN_NOTES = (
    "Уточнить у владельца требования к оборудованию и использовать в сообщении только полное подтверждённое "
    "условие владельца.",
    "Проверить в беседах, какие вопросы об оборудовании возникают у аудитории, и сверить ответы "
    "с полным описанием владельца.",
    "Clarify the equipment requirements with the owner and use only the complete confirmed owner terms "
    "in communication.",
    "Check in interviews which equipment questions the audience raises and compare the answers "
    "with the complete owner description.",
)
PLAN_NOTES = DEMO_PLAN_NOTES + EQUIPMENT_PLAN_NOTES
# Appended to the existing field descriptions; SOURCE/digit guidance is kept verbatim.
DEMO_TEXT_NOTE = ("Free prose must not mention demonstration or demo materials; "
                  "a current demo fact uses its exact SOURCE token where listed. "
                  "Write the content itself; never a kind label or a schema key. "
                  "Free prose must not mention equipment; an owner equipment condition appears only "
                  "through its exact SOURCE token where listed.")
DEMO_ITEMS_NOTE = ("Free prose must not mention demonstration or demo materials. To plan a NEW demo "
                   "material, choose one exact listed demo-plan sentence. "
                   "Write the content itself; never a kind label or a schema key. "
                   "Free prose must not mention equipment; use an exact SOURCE token for an owner "
                   "equipment condition, or one exact listed equipment-plan sentence.")


def with_note(description, note):
    return note if not description else description + " " + note


def _fail():
    raise ModuleExecutionContractError("Invalid CMO demo-plan wire") from None


def _free_branch(field):
    branches = field["anyOf"] if "anyOf" in field else (field,)
    free = [branch for branch in branches if branch.get("pattern") == QUALITATIVE_GENERATION_PATTERN]
    if len(free) != 1 or free[0].get("type") != "string":
        _fail()
    return free[0]


def demo_free_prose(field, *, plans=False):
    """Restrict the single free-prose branch; optionally add the closed plan branch."""
    result = deepcopy(field)
    free = _free_branch(result)
    free["pattern"] = DEMO_FREE_PATTERN
    if not plans:
        result["description"] = with_note(result.get("description"), DEMO_TEXT_NOTE)
        return result
    maximum = free["maxLength"]
    notes = [note for note in PLAN_NOTES if len(note) <= maximum]
    if len(notes) != len(PLAN_NOTES):
        _fail()
    plan = {"type": "string", "enum": notes, "description": (
        "Exact closed plan for a NEW demo material or for clarifying equipment terms; "
        "the server keeps the sentence unchanged.")}
    if "anyOf" in result:
        result["anyOf"].append(plan)
        result["description"] = with_note(result.get("description"), DEMO_ITEMS_NOTE)
        return result
    return {"description": DEMO_ITEMS_NOTE, "anyOf": [result, plan]}
