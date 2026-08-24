from __future__ import annotations

import hashlib
import json
import re
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any, Iterable

from app.module_registry import InputRequirement, ModuleDescriptor, ModuleId, ModuleRegistry, ModuleRegistryNotFoundError

from .contracts import (
    AuthorizedContextFact,
    BlockingQuestion,
    ContextPacket,
    DataSufficiency,
    ExecutionReadiness,
    GraphDependency,
    InputClassification,
    OrchestrationPlan,
    PlanNode,
    PlanningContext,
    PlanningStatus,
    PlanningStopCondition,
    RequestInterpretation,
    ScopedInput,
    StructuralValidity,
)
from .errors import InvalidInterpretationError, UnknownModulePlanningError
from .validation import PlanValidator, SUPPORTED_SCENARIOS


_KEY_RE = re.compile(r"[^a-z0-9]+")

_POSITIONING_OUTPUTS = {
    ModuleId.MARKET_ANALYSIS: (
        "market_definition", "segments", "audience_findings", "market_opportunities", "research_gaps.",
    ),
    ModuleId.COMPETITOR_ANALYSIS: (
        "competitor_set", "observable_positioning", "offers", "proof", "patterns", "market_gaps", "differentiation_hypotheses.",
    ),
    ModuleId.POSITIONING: (
        "category", "target", "value_proposition", "differentiation", "RTB", "positioning_statement",
        "USP_directions", "offer", "message_hierarchy", "claim_risks", "validation_plan.",
    ),
}

_POSITIONING_INPUTS = {
    "market_analysis": (
        ("product_or_category", InputClassification.REQUIRED),
        ("geographic_scope", InputClassification.BLOCKING),
        ("business_model", InputClassification.PREFERRED),
    ),
    "competitor_analysis": (
        ("competitor_or_category_scope", InputClassification.REQUIRED),
        ("observable_evidence", InputClassification.BLOCKING),
        ("target_segment", InputClassification.PREFERRED),
    ),
    "positioning": (
        ("product", InputClassification.REQUIRED),
        ("target_or_target_hypothesis", InputClassification.REQUIRED),
        ("customer_job_or_need", InputClassification.REQUIRED),
        ("relevant_alternative", InputClassification.REQUIRED),
        ("product_truth", InputClassification.BLOCKING),
        ("existing_proof", InputClassification.PREFERRED),
    ),
}


def _canonical_key(value: str) -> str:
    return _KEY_RE.sub("_", value.casefold()).strip("_")


def _stable_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict) or hasattr(value, "items"):
        return {str(key): _stable_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_stable_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_stable_value(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if is_dataclass(value):
        return {item.name: _stable_value(getattr(value, item.name)) for item in fields(value)}
    raise InvalidInterpretationError(f"unsupported non-deterministic context value: {type(value).__name__}")


class MarketingOrchestratorPlanner:
    """Side-effect-free planner for the two approved deterministic scenarios."""

    supported_scenarios = SUPPORTED_SCENARIOS

    def __init__(self, registry: ModuleRegistry | None = None) -> None:
        self._registry = registry or ModuleRegistry.load()
        self._validator = PlanValidator(self._registry)
        self._registry_fingerprint = self._fingerprint_registry()

    def plan(
        self,
        interpretation: RequestInterpretation,
        context: PlanningContext | None = None,
    ) -> OrchestrationPlan:
        if not isinstance(interpretation, RequestInterpretation):
            raise InvalidInterpretationError("planner accepts RequestInterpretation only")
        context = context or PlanningContext()
        if not isinstance(context, PlanningContext):
            raise InvalidInterpretationError("planner accepts PlanningContext only")

        if interpretation.requested_module is not None:
            plan = self._plan_single_module(interpretation, context)
        elif interpretation.scenario_key == "new_positioning_v1":
            plan = self._plan_new_positioning(interpretation, context)
        else:
            plan = self._unsupported_plan(interpretation, context)

        known_keys = frozenset(
            _canonical_key(fact.key)
            for node in plan.nodes
            for fact in (*node.context_packet.relevant_project_context, *node.context_packet.known_facts)
        )
        self._validator.validate(plan, known_input_keys=known_keys)
        return plan

    def _plan_single_module(self, interpretation: RequestInterpretation, context: PlanningContext) -> OrchestrationPlan:
        try:
            descriptor = self._registry.get(interpretation.requested_module)  # type: ignore[arg-type]
        except ModuleRegistryNotFoundError as exc:
            raise UnknownModulePlanningError(str(exc)) from exc
        scenario_key = "explicit_single_module_v1"
        node_id = descriptor.module_id.value.casefold()
        packet = self._context_packet(context, descriptor.module_id, scenario_key, (), interpretation.constraints)
        inputs = self._descriptor_inputs(descriptor, packet)
        node = PlanNode(
            node_id=node_id,
            module_id=descriptor.module_id,
            objective=interpretation.decision_goal,
            scoped_inputs=inputs,
            expected_outputs=descriptor.outputs,
            quality_gate=descriptor.quality_gate,
            context_packet=packet,
        )
        return self._finalize(interpretation, context, scenario_key, (node,), ())

    def _plan_new_positioning(self, interpretation: RequestInterpretation, context: PlanningContext) -> OrchestrationPlan:
        scenario_key = "new_positioning_v1"
        definitions = (
            ("market_analysis", ModuleId.MARKET_ANALYSIS, (), "evidence_analysis", True),
            ("competitor_analysis", ModuleId.COMPETITOR_ANALYSIS, (), "evidence_analysis", True),
            ("positioning", ModuleId.POSITIONING, ("competitor_analysis", "market_analysis"), None, False),
        )
        nodes = []
        for node_id, module_id, dependency_refs, parallel_group, parallelizable in definitions:
            descriptor = self._registry.get(module_id)
            packet = self._context_packet(context, module_id, scenario_key, dependency_refs, interpretation.constraints)
            inputs = self._scenario_inputs(node_id, packet)
            nodes.append(
                PlanNode(
                    node_id=node_id,
                    module_id=module_id,
                    objective=self._objective_for(module_id, interpretation),
                    scoped_inputs=inputs,
                    expected_outputs=_POSITIONING_OUTPUTS[module_id],
                    quality_gate=descriptor.quality_gate,
                    dependency_references=dependency_refs,
                    next_if_pass="positioning" if parallelizable else None,
                    next_if_fail="BLOCKING_INPUT_MISSING",
                    parallel_group=parallel_group,
                    parallelizable=parallelizable,
                    context_packet=packet,
                )
            )
        dependencies = (
            GraphDependency("competitor_analysis", "positioning"),
            GraphDependency("market_analysis", "positioning"),
        )
        return self._finalize(interpretation, context, scenario_key, tuple(nodes), dependencies)

    def _unsupported_plan(self, interpretation: RequestInterpretation, context: PlanningContext) -> OrchestrationPlan:
        scenario_key = interpretation.scenario_key or ""
        return OrchestrationPlan(
            plan_id=self._plan_id(interpretation, context, scenario_key),
            scenario_key=scenario_key,
            nodes=(),
            dependencies=(),
            structural_validity=StructuralValidity.INVALID,
            data_sufficiency=DataSufficiency.INSUFFICIENT,
            planning_status=PlanningStatus.UNSUPPORTED,
            execution_readiness=ExecutionReadiness.PLANNING_ONLY,
            limitations=(f"unsupported planning scenario: {scenario_key}",),
            assumptions=context.assumptions,
            stop_condition=PlanningStopCondition.UNSUPPORTED_SCENARIO,
        )

    def _finalize(
        self,
        interpretation: RequestInterpretation,
        context: PlanningContext,
        scenario_key: str,
        nodes: tuple[PlanNode, ...],
        dependencies: tuple[GraphDependency, ...],
    ) -> OrchestrationPlan:
        questions: list[BlockingQuestion] = []
        limitations: list[str] = []
        seen_questions: set[str] = set()
        for node in nodes:
            for item in node.scoped_inputs:
                if item.present:
                    continue
                if item.classification in {InputClassification.REQUIRED, InputClassification.BLOCKING}:
                    key = item.key.casefold()
                    if key not in seen_questions and len(questions) < 3:
                        seen_questions.add(key)
                        questions.append(
                            BlockingQuestion(item.key, f"Provide {item.key.replace('_', ' ')}.", node.node_id)
                        )
                else:
                    limitations.append(f"{node.node_id}: missing {item.classification.value.casefold()} input {item.key}")
        questions_tuple = tuple(questions)
        limitations_tuple = tuple(dict.fromkeys(limitations))
        blocked = bool(questions_tuple)
        if blocked:
            sufficiency = DataSufficiency.INSUFFICIENT
        elif limitations_tuple:
            sufficiency = DataSufficiency.PARTIAL
        else:
            sufficiency = DataSufficiency.SUFFICIENT
        return OrchestrationPlan(
            plan_id=self._plan_id(interpretation, context, scenario_key),
            scenario_key=scenario_key,
            nodes=nodes,
            dependencies=dependencies,
            structural_validity=StructuralValidity.VALID,
            data_sufficiency=sufficiency,
            planning_status=PlanningStatus.BLOCKED if blocked else PlanningStatus.VALIDATED,
            execution_readiness=ExecutionReadiness.PLANNING_ONLY,
            blocking_questions=questions_tuple,
            limitations=limitations_tuple,
            assumptions=context.assumptions,
            stop_condition=PlanningStopCondition.BLOCKING_INPUT_MISSING if blocked else PlanningStopCondition.PLAN_COMPLETE,
        )

    def _context_packet(
        self,
        context: PlanningContext,
        module_id: ModuleId,
        scenario_key: str,
        dependency_refs: tuple[str, ...],
        request_constraints: tuple[str, ...],
    ) -> ContextPacket:
        relevant_project = self._relevant_facts(context.project_context, module_id, scenario_key)
        known = self._relevant_facts(context.known_facts, module_id, scenario_key)
        upstream = tuple(
            item for item in context.upstream_findings if item.producer_node_id in dependency_refs
        )
        evidence = tuple(
            dict.fromkeys(
                item for fact in (*relevant_project, *known) for item in fact.evidence
            )
        )
        confidences = {fact.confidence for fact in (*relevant_project, *known) if fact.confidence}
        confidence = next(iter(confidences)) if len(confidences) == 1 else ("MIXED" if confidences else "UNKNOWN")
        return ContextPacket(
            relevant_project_context=relevant_project,
            known_facts=known,
            upstream_findings=upstream,
            evidence=evidence,
            assumptions=tuple(context.assumptions),
            confidence=confidence,
            constraints=tuple(dict.fromkeys((*request_constraints, *context.constraints))),
            available_tools=context.available_tools,
        )

    @staticmethod
    def _relevant_facts(
        facts: Iterable[AuthorizedContextFact], module_id: ModuleId, scenario_key: str
    ) -> tuple[AuthorizedContextFact, ...]:
        selected = [
            fact for fact in facts
            if fact.authorized and (module_id in fact.module_relevance or scenario_key in fact.scenario_relevance)
        ]
        return tuple(sorted(selected, key=lambda fact: (fact.key.casefold(), fact.source, fact.confidence)))

    @staticmethod
    def _known_keys(packet: ContextPacket) -> frozenset[str]:
        return frozenset(
            _canonical_key(fact.key)
            for fact in (*packet.relevant_project_context, *packet.known_facts)
        )

    def _scenario_inputs(self, node_id: str, packet: ContextPacket) -> tuple[ScopedInput, ...]:
        known = self._known_keys(packet)
        return tuple(ScopedInput(key, classification, _canonical_key(key) in known) for key, classification in _POSITIONING_INPUTS[node_id])

    def _descriptor_inputs(self, descriptor: ModuleDescriptor, packet: ContextPacket) -> tuple[ScopedInput, ...]:
        known = self._known_keys(packet)
        mapping = (
            (InputRequirement.REQUIRED, InputClassification.REQUIRED),
            (InputRequirement.BLOCKING_FOR_STRONG_CONCLUSION, InputClassification.BLOCKING),
            (InputRequirement.PREFERRED, InputClassification.PREFERRED),
            (InputRequirement.OPTIONAL, InputClassification.OPTIONAL),
        )
        result = []
        for registry_classification, classification in mapping:
            for raw_key in descriptor.inputs[registry_classification]:
                key = _canonical_key(raw_key)
                if key:
                    result.append(ScopedInput(key, classification, key in known))
        return tuple(result)

    def _plan_id(self, interpretation: RequestInterpretation, context: PlanningContext, scenario_key: str) -> str:
        payload = {
            "interpretation": _stable_value(interpretation),
            "context": _stable_value(context),
            "registry_version": self._registry.version,
            "registry_fingerprint": self._registry_fingerprint,
            "scenario_key": scenario_key,
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _fingerprint_registry(self) -> str:
        payload = [
            {
                "module_id": item.module_id.value,
                "outputs": item.outputs,
                "quality_gate": item.quality_gate,
                "aliases": item.aliases,
                "availability": item.availability_status.value,
                "execution_binding": item.execution_binding is not None,
            }
            for item in self._registry.descriptors
        ]
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _objective_for(module_id: ModuleId, interpretation: RequestInterpretation) -> str:
        if module_id is ModuleId.MARKET_ANALYSIS:
            return f"Establish market and audience evidence for {interpretation.decision_goal}"
        if module_id is ModuleId.COMPETITOR_ANALYSIS:
            return f"Establish competitor and alternative evidence for {interpretation.decision_goal}"
        return interpretation.decision_goal
