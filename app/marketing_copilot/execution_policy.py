"""Allowlisted deterministic depth selection; proposals never execute anything."""
from types import MappingProxyType

from app.marketing_orchestrator import PlanningContext, PlanningInputKey
from app.module_registry import ModuleId, ModuleRegistry

from .context_resolver import has_value
from .contracts import CopilotContractError, ExecutionDecision, ExecutionMode, IntentKind, MarketingIntent, ReasonCode


_MODULES = MappingProxyType({
    IntentKind.POST_GENERATION: ModuleId.CREATOR,
    IntentKind.TEXT_EDITING: ModuleId.COPY_EDITOR,
    IntentKind.COMPETITOR_ANALYSIS: ModuleId.COMPETITOR_ANALYSIS,
})
_POSITIONING_KEYS = frozenset({
    PlanningInputKey.PRODUCT, PlanningInputKey.TARGET_OR_TARGET_HYPOTHESIS,
    PlanningInputKey.CUSTOMER_JOB_OR_NEED, PlanningInputKey.RELEVANT_ALTERNATIVE,
    PlanningInputKey.PRODUCT_TRUTH,
})


class ExecutionPolicy:
    def __init__(self, registry: ModuleRegistry | None = None):
        self._registry = registry or ModuleRegistry.load()

    @staticmethod
    def missing_positioning_inputs(context):
        keys = {
            fact.input_key for fact in (*context.project_context, *context.known_facts)
            if fact.authorized and has_value(fact.value) and (
                ModuleId.POSITIONING in fact.module_relevance
                or "explicit_single_module_v1" in fact.scenario_relevance
            )
        }
        return tuple(sorted(key.value for key in _POSITIONING_KEYS - keys))

    def decide(self, intent: MarketingIntent, context: PlanningContext) -> ExecutionDecision:
        if type(intent) is not MarketingIntent or type(context) is not PlanningContext:
            raise CopilotContractError("Policy requires MarketingIntent and resolved PlanningContext")
        intent = MarketingIntent.model_validate(intent)

        def decision(mode, reason, **selector):
            reasons = (reason,)
            if intent.external_evidence_required and reason is not ReasonCode.EXTERNAL_EVIDENCE_REQUIRED:
                reasons += (ReasonCode.EXTERNAL_EVIDENCE_REQUIRED,)
            return ExecutionDecision(intent=intent, mode=mode, reason_codes=reasons, **selector)

        def conversation(reason):
            return decision(ExecutionMode.CONVERSATION, reason)

        if intent.ambiguous:
            return conversation(ReasonCode.AMBIGUOUS_INTENT)
        if intent.kind is IntentKind.UNSUPPORTED:
            return conversation(ReasonCode.UNSUPPORTED_INTENT)
        if intent.confidence < 0.7:
            return conversation(ReasonCode.LOW_CONFIDENCE)
        if intent.kind is IntentKind.LEAD_FUNNEL_CALCULATION:
            if not intent.deterministic_calculation_required or intent.external_evidence_required:
                return conversation(ReasonCode.UNSUPPORTED_COMBINATION)
            return decision(ExecutionMode.DIRECT_TOOL, ReasonCode.DETERMINISTIC_CALCULATION,
                            tool_key="lead_funnel_calculator_v1")
        if intent.deterministic_calculation_required:
            return conversation(ReasonCode.UNSUPPORTED_COMBINATION)
        if intent.kind is IntentKind.CONVERSATION:
            return conversation(ReasonCode.CONVERSATION_REQUEST)
        if intent.kind in _MODULES:
            # Registry identity/metadata is checked; its execution_binding is never used.
            module = self._registry.get(_MODULES[intent.kind]).module_id
            return decision(ExecutionMode.SINGLE_MODULE, ReasonCode.SINGLE_MODULE_REQUEST, module_id=module)
        if intent.kind is IntentKind.POSITIONING:
            if intent.external_evidence_required:
                return conversation(ReasonCode.EXTERNAL_EVIDENCE_REQUIRED)
            if self.missing_positioning_inputs(context):
                return conversation(ReasonCode.POSITIONING_CONTEXT_MISSING)
            return decision(ExecutionMode.SINGLE_MODULE, ReasonCode.POSITIONING_CONTEXT_SUFFICIENT,
                            module_id=self._registry.get(ModuleId.POSITIONING).module_id)
        if intent.kind is IntentKind.COMPARATIVE_POSITIONING:
            for module in (ModuleId.COMPETITOR_ANALYSIS, ModuleId.POSITIONING):
                self._registry.get(module)
            return decision(ExecutionMode.WORKFLOW, ReasonCode.COMPARATIVE_ANALYSES_REQUIRED,
                            scenario_key="competitive_positioning_v1")
        if intent.kind is IntentKind.MARKETING_STRATEGY:
            return decision(ExecutionMode.WORKFLOW, ReasonCode.STRATEGY_WORKFLOW_REQUEST,
                            scenario_key="strategy_builder_v1")
        return conversation(ReasonCode.UNSUPPORTED_INTENT)
