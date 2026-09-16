"""Adapt proposals to existing planning contracts without invoking the planner."""
from app.marketing_orchestrator import PlanningContext, RequestInterpretation

from .contracts import CopilotContractError, ExecutionDecision, ExecutionMode


class OrchestratorAdapter:
    def adapt(self, decision: ExecutionDecision, context: PlanningContext) -> tuple[RequestInterpretation, PlanningContext]:
        if type(decision) is not ExecutionDecision or type(context) is not PlanningContext:
            raise CopilotContractError("Adapter requires ExecutionDecision and resolved PlanningContext")
        decision = ExecutionDecision.model_validate(decision)
        if decision.mode not in {ExecutionMode.SINGLE_MODULE, ExecutionMode.WORKFLOW}:
            raise CopilotContractError("Conversation/direct-tool proposals do not have an Orchestrator selector")
        intent = decision.intent
        constraints = (*intent.constraints, *context.constraints)
        assumptions = context.assumptions
        business_goal = intent.business_goal
        if business_goal is None:
            # Legacy interpretation requires non-empty business_goal; preserve absence
            # explicitly instead of fabricating a commercial objective.
            business_goal = "UNSPECIFIED"
            assumptions += ("Business goal was not supplied; no business objective is inferred.",)
        if intent.external_evidence_required:
            constraints += ("External evidence is required; supplied references are not verified evidence.",)
        if intent.provided_urls or intent.source_references:
            # References remain in decision.intent until a caller resolves/authorizes
            # them. Do not promote arbitrary reference text to facts or instructions.
            constraints += ("Request references require caller resolution and authorization before use as evidence.",)
        interpretation = RequestInterpretation(
            requested_output=intent.requested_output, decision_goal=intent.decision_goal,
            business_goal=business_goal, intent=intent.kind.value, object=intent.subject,
            depth=decision.mode.value, mode="PLANNING_ONLY", constraints=constraints,
            requested_module=decision.module_id, scenario_key=decision.scenario_key,
        )
        resolved = PlanningContext(
            project_context=context.project_context, known_facts=context.known_facts,
            upstream_findings=context.upstream_findings, assumptions=assumptions,
            constraints=constraints, available_tools=context.available_tools,
        )
        return interpretation, resolved
