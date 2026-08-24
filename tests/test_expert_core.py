from __future__ import annotations

import hashlib
from importlib import resources
from pathlib import Path
import re

import pytest

from app.prompts.expert_core import (
    EXPERT_CORE_VERSION,
    ExpertCoreResourceError,
    load_expert_core,
)
from app.services.expert_instruction_composer import (
    EXPERT_CORE_END,
    EXPERT_CORE_START_PREFIX,
    RESPONSE_MODE_START,
    SPECIALIZED_MODULE_START,
    ExpertInstructionComposer,
    ExpertInstructionCompositionError,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_NORMALIZED_SHA256 = (
    "5dad2b61b14c6a137668bd7ed0a5ee3b5cff45235d7c79726337b1e3529d72f9"
)

EXPECTED_SECTION_TITLES = (
    "ПЯТЬ УРОВНЕЙ МАРКЕТИНГОВОГО МЫШЛЕНИЯ",
    "ГЛАВНАЯ ЗАДАЧА",
    "НИКАКИХ ГАРАНТИЙ РЕЗУЛЬТАТА",
    "НЕ ОТВЕЧАЙ МЕХАНИЧЕСКИ",
    "ROOT PROBLEM",
    "EVIDENCE FIRST",
    "НЕ ЗАМЕНЯЙ ДАННЫЕ ФРЕЙМВОРКОМ",
    "КЛАССИФИКАЦИЯ ВЫВОДОВ",
    "CONFIDENCE",
    "НЕ ПРИДУМЫВАЙ ДАННЫЕ",
    "DATA SUFFICIENCY",
    "BUSINESS BEFORE VANITY METRICS",
    "CTR, CPC И CPL НЕ РАВНЫ БИЗНЕС-УСПЕХУ",
    "ЭКОНОМИКА",
    "БИЗНЕС-МОДЕЛЬ ИМЕЕТ ЗНАЧЕНИЕ",
    "ПРИЧИННОСТЬ",
    "ATTRIBUTION ≠ CAUSALITY",
    "НЕ ОПТИМИЗИРУЙ ЛОКАЛЬНО ЦЕНОЙ СИСТЕМЫ",
    "CUSTOMER REALITY",
    "CUSTOMER JOURNEY НЕ ОБЯЗАН БЫТЬ ЛИНЕЙНЫМ",
    "CUSTOMER VALUE BEFORE COMMUNICATION TRICKS",
    "PROOF",
    "DIFFERENTIATION ≠ FABRICATED UNIQUENESS",
    "BRAND + PERFORMANCE",
    "МЕНТАЛЬНАЯ И ФИЗИЧЕСКАЯ ДОСТУПНОСТЬ",
    "BRAND CONSISTENCY",
    "КАНАЛ — НЕ СТРАТЕГИЯ",
    "CURRENTNESS",
    "RUSSIA CONTEXT",
    "LEGAL BOUNDARY",
    "ETHICS",
    "ПСИХОЛОГИЯ БЕЗ МАНИПУЛЯЦИИ",
    "НЕ ИСПОЛЬЗУЙ УСТАРЕВШИЕ МАРКЕТИНГОВЫЕ ДОГМЫ",
    "SYNTHETIC AI DATA",
    "НЕ ОПТИМИЗИРУЙ КОЛИЧЕСТВО МАРКЕТИНГА",
    "ПРИОРИТИЗАЦИЯ",
    "RECOMMENDATION STANDARD",
    "ALTERNATIVES",
    "RISK",
    "TESTABILITY",
    "НЕ СОЗДАВАЙ ПСЕВДОТОЧНОСТЬ",
    "СТИЛЬ РАБОТЫ",
    "КРИТИКА ИДЕИ",
    "ОБЪЯСНИМОСТЬ",
    "RESPONSE ADAPTATION",
    "LEARNING MODE",
    "USER MATERIALS",
    "DATA QUALITY",
    "TEMPORAL CONSISTENCY",
    "FIRST-PARTY DATA PRIORITY",
    "NO CHANNEL OR FRAMEWORK FETISH",
    "STRATEGIC COHERENCE",
    "OPERATIONAL REALITY",
    "REVERSIBILITY",
    "DO NOT OVERANALYZE",
    "NON-NEGOTIABLE RULES",
    "FINAL QUALITY CONTROL",
    "PRIMARY PRINCIPLE",
    "FINAL PRINCIPLE",
)

EXPECTED_NEVER = (
    "гарантировать маркетинговый результат",
    "выдумывать данные",
    "выдумывать исследования",
    "выдумывать customer quotes",
    "выдавать AI simulation за evidence",
    "путать correlation с causation",
    "путать lead с customer",
    "путать revenue с profit",
    "принимать CTR/CPC/CPL за конечный business result",
    "использовать fake urgency",
    "использовать fake scarcity",
    "использовать fake reviews",
    "создавать dark patterns",
    "скрывать существенные ограничения",
    "выдавать предположение за факт",
    "использовать устаревший dynamic fact без проверки, если он влияет на решение",
    "рекомендовать масштабирование без учёта economics",
    "выбирать framework только ради формы",
)

EXPECTED_ALWAYS = (
    "связывать маркетинг с бизнесом",
    "учитывать клиента",
    "искать наиболее вероятную root cause",
    "отделять evidence от hypothesis",
    "обозначать critical assumptions",
    "калибровать confidence",
    "учитывать альтернативы",
    "учитывать economics",
    "учитывать downstream effect",
    "учитывать measurement",
    "учитывать риски",
    "сохранять practical focus",
)


def normalize_initial_import(value: str) -> str:
    value = value.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip(" \t") for line in value.split("\n")).rstrip("\n")


def _normalize_policy_item(value: str) -> str:
    return value.strip().removeprefix("- ").rstrip(";.")


def _extract_group(section: str, name: str, next_name: str | None) -> tuple[str, ...]:
    start = section.index(f"{name}:") + len(name) + 1
    end = section.index(f"{next_name}:", start) if next_name else len(section)
    return tuple(
        _normalize_policy_item(line)
        for line in section[start:end].splitlines()
        if line.strip().startswith("- ")
    )


def test_expert_core_version_and_packaged_resource_are_available():
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", EXPERT_CORE_VERSION)
    resource = resources.files("app.prompts.expert_core").joinpath("v1.0.0.md")
    assert resource.is_file()
    assert load_expert_core() == resource.read_text(encoding="utf-8").strip()


def test_expert_core_resource_is_in_current_docker_build_context():
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY . ." in dockerfile
    assert not (REPOSITORY_ROOT / ".dockerignore").exists()
    assert (
        REPOSITORY_ROOT / "app" / "prompts" / "expert_core" / "v1.0.0.md"
    ).is_file()


def test_expert_core_initial_import_has_expected_sections_and_checksum():
    content = load_expert_core()
    matches = re.findall(r"^# ([1-9]|[1-5][0-9])\. (.+)$", content, re.MULTILINE)
    assert [int(number) for number, _title in matches] == list(range(1, 60))
    assert tuple(title for _number, title in matches) == EXPECTED_SECTION_TITLES

    normalized = normalize_initial_import(content)
    assert hashlib.sha256(normalized.encode("utf-8")).hexdigest() == (
        EXPECTED_NORMALIZED_SHA256
    )


def test_expert_core_initial_import_has_exact_non_negotiable_groups():
    content = load_expert_core()
    start = content.index("# 56. NON-NEGOTIABLE RULES")
    end = content.index("# 57. FINAL QUALITY CONTROL", start)
    section = content[start:end]

    assert _extract_group(section, "NEVER", "ALWAYS") == EXPECTED_NEVER
    assert _extract_group(section, "ALWAYS", None) == EXPECTED_ALWAYS


def test_loader_rejects_invalid_or_unsupported_versions():
    with pytest.raises(ExpertCoreResourceError, match="Invalid"):
        load_expert_core("v1")
    with pytest.raises(ExpertCoreResourceError, match="Unsupported"):
        load_expert_core("2.0.0")


def test_runtime_python_files_do_not_duplicate_the_prompt_body():
    python_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPOSITORY_ROOT / "app").rglob("*.py")
    )
    assert "# 1. ПЯТЬ УРОВНЕЙ МАРКЕТИНГОВОГО МЫШЛЕНИЯ" not in python_sources
    assert "# 59. FINAL PRINCIPLE" not in python_sources

    product_docs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (REPOSITORY_ROOT / "docs" / "product").rglob("*.md")
    )
    assert "# 1. ПЯТЬ УРОВНЕЙ МАРКЕТИНГОВОГО МЫШЛЕНИЯ" not in product_docs
    assert "# 59. FINAL PRINCIPLE" not in product_docs


def test_composer_is_deterministic_and_preserves_component_order():
    composer = ExpertInstructionComposer()
    first = composer.compose("MODULE BODY", "RESPONSE BODY")
    second = composer.compose("MODULE BODY", "RESPONSE BODY")

    assert first == second
    assert first.expert_core_version == "1.0.0"
    assert first.component_identities == (
        "expert_core:1.0.0",
        "specialized_module",
        "response_mode",
    )
    assert first.rendered_text.count(EXPERT_CORE_START_PREFIX) == 1
    assert first.rendered_text.count(EXPERT_CORE_END) == 1
    assert first.rendered_text.index("APPLICATION INSTRUCTION PRECEDENCE") < (
        first.rendered_text.index("# EXPERT_CORE_PRODUCTION")
    )
    assert first.rendered_text.index("# EXPERT_CORE_PRODUCTION") < (
        first.rendered_text.index(SPECIALIZED_MODULE_START)
    )
    assert first.rendered_text.index(SPECIALIZED_MODULE_START) < (
        first.rendered_text.index("MODULE BODY")
    )
    assert first.rendered_text.index("MODULE BODY") < (
        first.rendered_text.index(RESPONSE_MODE_START)
    )
    assert first.rendered_text.index(RESPONSE_MODE_START) < (
        first.rendered_text.index("RESPONSE BODY")
    )


def test_composer_repeated_composition_is_idempotent():
    composer = ExpertInstructionComposer()
    composed = composer.compose("MODULE BODY")

    assert composer.compose(composed) is composed
    assert composed.rendered_text.count(EXPERT_CORE_START_PREFIX) == 1


@pytest.mark.parametrize(
    "component",
    [
        "<!-- EXPERT_CORE:1.0.0 -->",
        "<!-- /EXPERT_CORE -->",
        "<!-- SPECIALIZED_MODULE -->",
        "<!-- RESPONSE_MODE -->",
    ],
)
def test_composer_rejects_reserved_markers(component):
    composer = ExpertInstructionComposer()
    with pytest.raises(ExpertInstructionCompositionError, match="reserved marker"):
        composer.compose(f"module {component}")
    with pytest.raises(ExpertInstructionCompositionError, match="reserved marker"):
        composer.compose("module", f"response {component}")


def test_composer_fails_closed_for_invalid_or_empty_core():
    for loader in (
        lambda _version: "",
        lambda _version: "<!-- EXPERT_CORE:1.0.0 -->",
    ):
        composer = ExpertInstructionComposer(core_loader=loader)
        with pytest.raises(ExpertInstructionCompositionError):
            composer.compose("module")


def test_composer_rejects_invalid_active_version_before_loading():
    composer = ExpertInstructionComposer(
        core_loader=lambda _version: "core",
        version="version-one",
    )
    with pytest.raises(ExpertInstructionCompositionError, match="Invalid"):
        composer.compose("module")
