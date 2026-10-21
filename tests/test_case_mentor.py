"""Semantic grounding checks against real executor outputs, no external provider."""
from types import SimpleNamespace

import pytest

from app.marketing_copilot.api_errors import CopilotAPIError
from app.marketing_copilot.mentor import explanation, paragraphs
from app.module_registry import ModuleId
from tests.test_strategy_intelligence import run, valid_request, positioning


def case():
    result = run(valid_request(ModuleId.VIRTUAL_CMO))
    packet = valid_request(ModuleId.VIRTUAL_CMO).context_packet
    plan = SimpleNamespace(nodes=[SimpleNamespace(node_id="virtual_cmo", module_id=ModuleId.VIRTUAL_CMO, context_packet=packet)])
    return plan, {"positioning": positioning(), "virtual_cmo": result}


def test_eight_sections_use_saved_business_and_decisions_without_mutating_source():
    plan, accepted = case()
    result = accepted["virtual_cmo"]
    before = repr(result)
    public = explanation("a" * 64, plan, accepted)
    sections = {section.key: section.paragraphs for section in public.sections}
    assert len(sections) == 8
    assert "Grow qualified demand" in sections["goal"]
    assert any("Scheduling software" in value for value in sections["inputs"])
    assert any("Validate the supplied scheduling hypothesis" in value for value in sections["rationale"])
    assert any("Сохранённое основание" in value for value in sections["rationale"])
    assert any("Отдельное экономическое обоснование не сохранено" in value for value in sections["limitations"])
    assert any("Отдельный план эксперимента не сохранён" in value for value in sections["verification"])
    assert any("превосходство" in value for value in sections["alternatives"])
    assert repr(result) == before


def test_no_source_strategy_cannot_be_explained_as_success():
    plan, accepted = case()
    with pytest.raises(CopilotAPIError) as error:
        explanation("a" * 64, plan, {"positioning": accepted["positioning"]})
    assert error.value.status == 409


def test_saved_experiments_keep_expected_signal_separate_from_actual_results():
    plan, accepted = case()
    accepted["experiments"] = run(valid_request(ModuleId.EXPERIMENTS))
    public = explanation("a" * 64, plan, accepted)
    verification = next(section.paragraphs for section in public.sections if section.key == "verification")
    assert "Метрика: Qualified inquiry rate" in verification
    assert any(value.startswith("Ожидаемый сигнал (не фактический результат):") for value in verification)
    assert any(value.startswith("Условие отказа:") for value in verification)


def test_large_paragraphs_preserve_all_text():
    text = "Данные😀" * 2000
    chunks = paragraphs([text])
    assert "".join(chunks) == text
    assert max(map(len, chunks)) <= 4000


def test_full_strategy_lineage_and_followup_preserve_large_legal_saved_output():
    """Seven nodes at schema bounds exceed the former 128/256 paragraph caps."""
    import json
    from app.marketing_copilot.mentor_contracts import MentorAnswer, SavedFeedback
    from app.marketing_orchestrator import AuthorizedContextFact, ContextPacket
    from app.marketing_orchestrator.quality_gates import QualityGateEvaluator
    from app.marketing_orchestrator.quality_gates.contracts import (
        AuthorityStatus, ClaimLineageType, ClaimType, Confidence, EvidenceRecord,
        EvidenceSourceClass, EvidenceSufficiency, EvaluationBatch, ModuleResultStatus,
        LimitationReason, LimitationRecord, Materiality, NormalizedClaim, NormalizedModuleResult,
    )
    from app.module_execution import ModuleExecutionResult
    from app.module_execution.acceptance import fully_accepted
    from app.module_execution.executors.schemas import CompetitorOutput, PositioningOutput
    from app.module_execution.executors.intelligence_schemas import StrategyOutput, ExperimentsOutput
    from app.module_registry import ModuleRegistry
    from app.orchestration_runtime.serialization import result_to_json

    registry = ModuleRegistry.load("1.3.0")
    accepted = {}
    statements = {}
    alphabet = "abcdefghijklmnopqrstuvwxyz"

    def full_text(prefix, length=4000):
        return prefix + " текст" * ((length - len(prefix)) // 6) + "я" * ((length - len(prefix)) % 6)

    def result(key, module, *, parents=(), strategy=False, experiments=False):
        outputs, claims = [], []
        evidence_id = "evd_" + key
        for index, name in enumerate(registry.get(module).outputs):
            text = full_text(key + " " + name + " ")
            refs = list(parents[index % 2::2]) if module is ModuleId.POSITIONING else list(parents)
            statement = dict(output_name=name, text=text, kind="HYPOTHESIS", confidence="LOW",
                evidence_ids=[] if refs else [evidence_id], parent_claim_ids=refs)
            value = text
            if strategy:
                items = [full_text("Действие " + alphabet[j] + " ", 300) for j in range(1 if name == "main_growth_constraint" else 3)]
                statement.update(items=items, numeric_context=[])
                value = json.dumps({"summary": text, "items": items, "numeric_context": []}, ensure_ascii=False)
            outputs.append(statement)
            claims.append(NormalizedClaim(claim_id=f"clm_{key}_{index}", declared_output_name=name,
                claim_type=ClaimType.HYPOTHESIS, confidence=Confidence.LOW,
                authority_status=AuthorityStatus.WITHIN_SCOPE, value=value,
                lineage_type=ClaimLineageType.DERIVES if refs else ClaimLineageType.ORIGINAL,
                parent_claim_ids=tuple(refs), evidence_ids=() if refs else (evidence_id,)))
        raw = dict(outputs=outputs, assumptions=[full_text("Допущение " + alphabet[i] + " ") for i in range(12)],
            limitations=[full_text("Ограничение " + alphabet[i] + " ") for i in range(12)])
        if experiments:
            raw["experiments"] = [dict(hypothesis=full_text("Гипотеза " + alphabet[i], 300),
                target_metric=full_text("Метрика " + alphabet[i], 300), intervention=full_text("Изменение " + alphabet[i], 300),
                expected_signal=full_text("Ожидание " + alphabet[i], 300), failure_condition=full_text("Отказ " + alphabet[i], 300),
                minimum_required_inputs=[full_text("Данные " + alphabet[j], 300) for j in range(5)],
                time_resource_constraints=[full_text("Ресурс " + alphabet[j], 300) for j in range(8)],
                related_strategic_claim_ids=list(parents[:8])) for i in range(3)]
        schema = StrategyOutput if strategy else ExperimentsOutput if experiments else (
            PositioningOutput if module is ModuleId.POSITIONING else CompetitorOutput)
        if module is ModuleId.MARKET_ANALYSIS:
            from app.module_execution.executors.intelligence_schemas import MarketOutput
            schema = MarketOutput
        payload = schema.model_validate(raw).model_dump(mode="json")
        item = ModuleExecutionResult(module_id=module, schema_version=module.value.lower() + ".payload.v1",
            payload=payload, normalized_result=NormalizedModuleResult(result_id="res_" + key, module_id=module,
                module_status=ModuleResultStatus.PASS_WITH_LIMITATIONS, claims=tuple(claims),
                evidence=(EvidenceRecord(evidence_id, EvidenceSourceClass.FIRST_PARTY, "User-supplied context; not independently verified"),),
                limitations=tuple(LimitationRecord("lim_" + key + "_" + str(index),
                    LimitationReason.INCOMPLETE_COVERAGE, Materiality.MATERIAL, related_result_ids=("res_" + key,),
                    description=text) for index, text in enumerate(raw["limitations"])),
                evidence_sufficiency=EvidenceSufficiency.LIMITED))
        accepted[key], statements[key] = item, outputs
        result_to_json(item)  # Same bounded persistence codec as saved graph results.
        return [claim.claim_id for claim in claims]

    roots = []
    for key in ("competitor_a", "competitor_b", "competitor_c"):
        roots.extend(result(key, ModuleId.COMPETITOR_ANALYSIS))
    roots.extend(result("market", ModuleId.MARKET_ANALYSIS))
    positioning_ids = result("positioning", ModuleId.POSITIONING, parents=roots)
    strategy_ids = result("virtual_cmo", ModuleId.VIRTUAL_CMO, parents=positioning_ids, strategy=True)
    result("experiments", ModuleId.EXPERIMENTS, parents=strategy_ids, experiments=True)
    # Check actual normalized contracts and Quality Gates acceptance, rather
    # than injecting untyped claims that a persisted graph would reject.
    manifest = QualityGateEvaluator().evaluate(EvaluationBatch(batch_id="bat_large_mentor",
        results=tuple(item.normalized_result for item in accepted.values()))).synthesis_manifest
    assert all(fully_accepted(item, manifest.accepted_result_ids, manifest.accepted_claim_ids) for item in accepted.values())
    packet = ContextPacket(known_facts=tuple(AuthorizedContextFact("fact." + key, key, full_text(key + " "))
        for key in ("business_goal", "product", "target_or_target_hypothesis", "customer_job_or_need",
            "relevant_alternative", "product_truth", "existing_proof", "geography", "economics", "message")),
        assumptions=tuple(full_text("Входное допущение " + alphabet[i] + " ", 1000) for i in range(12)),
        constraints=tuple(full_text("Входной ресурс " + alphabet[i] + " ", 1000) for i in range(12)),
        open_questions=tuple(full_text("Входной вопрос " + alphabet[i] + " ", 1000) for i in range(12)))
    plan = SimpleNamespace(nodes=[SimpleNamespace(node_id="virtual_cmo", module_id=ModuleId.VIRTUAL_CMO, context_packet=packet)])
    public = explanation("a" * 64, plan, accepted)
    rationale = next(section for section in public.sections if section.key == "rationale")
    assert len(rationale.paragraphs) > 128
    restored = "".join(rationale.paragraphs)
    for key in ("competitor_a", "competitor_b", "competitor_c", "market", "positioning"):
        assert all(statement["text"] in restored for statement in statements[key])
    selected = {"goal", "principle", "rationale", "verification", "takeaway"}
    values = ["Разбор использует сохранённый кейс."]
    values.extend(value for section in public.sections if section.key in selected for value in [section.title, *section.paragraphs])
    for index in range(10):
        report = SavedFeedback(run_id="a" * 64, outcome="worked", notes=full_text("Отчёт " + alphabet[index], 2000),
            metrics=full_text("Метрики " + alphabet[index], 2000))
        values.extend(["Сообщение пользователя, не независимо проверено", report.notes, report.metrics])
    answer = MentorAnswer(run_id="a" * 64, question="Разберите сохранённый кейс", focus="overview", paragraphs=paragraphs(values))
    assert len(answer.paragraphs) > 256
    assert "".join(answer.paragraphs) == "".join(values)
