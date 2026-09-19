"""One internal application entry point. Providers and persistence are injected."""
import hashlib
import json
from dataclasses import replace
from socket import gaierror

import httpx
from pydantic import ValidationError

from app.marketing_orchestrator import AuthorizedContextFact, PlanningInputKey, PlanningStatus
from app.marketing_orchestrator.errors import InvalidInterpretationError
from app.marketing_orchestrator.quality_gates.contracts import EvaluationBatch
from app.marketing_orchestrator.quality_gates.errors import QualityGateContractError
from app.marketing_tools import ToolInputNeeded
from app.module_execution import ModuleExecutionRequest
from app.module_execution.acceptance import fully_accepted
from app.module_registry import ModuleId, ModuleResultStatus
from app.orchestration_runtime.errors import CompilationError
from app.services.safe_http import UnsafeURL
from .application_contracts import (
    Clarification, CopilotExecutionResult, CopilotRequest, ResultKind, WorkflowStarted,
)
from .context_resolver import ContextEntry
from .contracts import CopilotContractError, ExecutionMode, IntentKind, ReasonCode


def identity(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode()).hexdigest()


def source_entries(entries):
    """Canonicalize the executor's legacy URL slot before resolving precedence."""
    canonical = PlanningInputKey.COMPETITOR_OR_CATEGORY_SCOPE
    return tuple(ContextEntry(canonical.value, replace(entry.fact, label=canonical.value, input_key=canonical))
                 if entry.fact.label in {"competitor_url", canonical.value} and entry.fact.input_key is None else entry
                 for entry in entries)


class MarketingCopilotService:
    def __init__(self, *, interpreter, resolver, policy, adapter, planner, compiler,
                 metadata, dispatcher, evaluator, graph_service, tools):
        self.interpreter, self.resolver, self.policy = interpreter, resolver, policy
        self.adapter, self.planner, self.compiler = adapter, planner, compiler
        self.metadata, self.dispatcher, self.evaluator = metadata, dispatcher, evaluator
        self.graph_service, self.tools = graph_service, tools

    async def execute(self, request: CopilotRequest) -> CopilotExecutionResult:
        if type(request) is not CopilotRequest:
            raise CopilotContractError("Expected CopilotRequest")
        request.__post_init__()
        intent = await self.interpreter.interpret(request.message)
        entries = list(source_entries(request.current_request))
        # Only literal request references, verified by the interpreter, enter as targets.
        # Existing explicit entries (including empty masks) retain precedence.
        # An owned-source declaration requires explicitly scoped competitor context;
        # raw message URLs cannot assign roles in this mixed-source request.
        keys = {entry.semantic_key for entry in entries}
        # Presence, including empty masks, declares caller-scoped source roles.
        # Other literal URLs may be market sources or explicitly ignored.
        scoped_source_roles = keys & {
            "competitor_urls", PlanningInputKey.COMPETITOR_OR_CATEGORY_SCOPE.value,
            "market_source_urls", "market_sources",
        }
        legacy_competitor_urls = not scoped_source_roles and request.owned_site_url is None and intent.kind in {
            IntentKind.COMPETITOR_ANALYSIS, IntentKind.COMPARATIVE_POSITIONING,
        }
        if legacy_competitor_urls and len(intent.provided_urls) == 1:
            key = PlanningInputKey.COMPETITOR_OR_CATEGORY_SCOPE
            if key.value not in keys:
                entries.append(ContextEntry(key.value, AuthorizedContextFact(
                    fact_id="request.competitor.source", label=key.value, value=intent.provided_urls[0],
                    input_key=key, source="literal current request URL; unverified fetch target",
                    module_relevance=frozenset({ModuleId.COMPETITOR_ANALYSIS}),
                )))
        context = self.resolver.resolve(
            current_request=tuple(entries), project_run=source_entries(request.project_run),
            owned_site_context=request.owned_site_context,
            brand_profile=source_entries(request.brand_profile), conversation=source_entries(request.conversation),
            authorized_upstream_findings=request.authorized_upstream_findings,
            available_tools=request.available_tools, assumptions=request.assumptions, constraints=request.constraints,
        )
        decision = self.policy.decide(intent, context)

        def result(kind, **payload):
            return CopilotExecutionResult(request_id=request.request_id,
                execution_id=identity("copilot.request.v1", request.actor_id, request.request_id),
                decision=decision, kind=kind, **payload)

        def needs(code, alternatives=(("request_context",),), reasons=()):
            return result(ResultKind.NEEDS_INPUT, clarification=Clarification(code, alternatives, reasons))

        if legacy_competitor_urls and len(intent.provided_urls) > 1:
            return needs("single_competitor_required", (("one_competitor_url",),))

        if decision.mode is ExecutionMode.CONVERSATION:
            if ReasonCode.CONVERSATION_REQUEST in decision.reason_codes:
                return result(ResultKind.CONVERSATION, conversation_delegate=True)
            return needs(decision.reason_codes[0].value)
        if decision.mode is ExecutionMode.DIRECT_TOOL:
            tool = self.tools.resolve(decision.tool_key)
            try:
                inputs = request.calculation if request.calculation is not None else tool.parse(request.message)
                output = tool.execute(inputs)
            except ToolInputNeeded as exc:
                return needs(exc.code, exc.alternatives)
            except ValidationError:
                return needs("invalid_calculation_range", (("valid_numeric_parameters",),))
            return result(ResultKind.DIRECT_RESULT, direct_result=output)

        interpretation, scoped = self.adapter.adapt(decision, context)
        try:
            plan = self.planner.plan(interpretation, scoped)
        except InvalidInterpretationError:
            if interpretation.scenario_key != "strategy_builder_v1":
                raise
            return needs("invalid_strategy_research", (("up_to_three_valid_competitor_urls",),))
        if plan.planning_status is not PlanningStatus.VALIDATED:
            questions = tuple(q.input_key.value for q in plan.blocking_questions)
            return needs("planning_" + plan.planning_status.value.lower(), (questions or ("supported_request",),))
        if decision.mode is ExecutionMode.WORKFLOW:
            try:
                compiled = self.compiler.compile(plan)
            except CompilationError:
                return needs("unsupported_execution_plan")
            if self.graph_service is None:
                return needs("workflow_capability_unavailable")
            # Identity deliberately excludes plan: the graph service compares persisted
            # compiled identity and raises conflict for another plan under this key.
            run_id = identity("copilot.run.v1", request.actor_id, request.request_id)
            await self.graph_service.start_compiled_run(owner_id=request.actor_id, run_id=run_id, plan=compiled)
            return result(ResultKind.WORKFLOW_STARTED, workflow=WorkflowStarted(run_id, compiled.source_plan_id))

        node = plan.nodes[0]
        binding = self.metadata.get(node.module_id).execution_binding
        if binding is None:
            return needs("module_not_execution_bound")
        execution_id = identity("copilot.module.v1", request.actor_id, request.request_id, plan.plan_id)
        invocation = ModuleExecutionRequest(
            execution_id=execution_id, module_id=node.module_id, objective=node.objective,
            expected_outputs=node.expected_outputs, context_packet=node.context_packet,
        )
        try:
            output = await self.dispatcher.dispatch(binding, invocation)
        except (httpx.HTTPError, TimeoutError, UnsafeURL, gaierror):
            return needs("provider_unavailable", (("accessible_source_or_retry",),))
        normalized = output.normalized_result
        try:
            evaluation = self.evaluator.evaluate(EvaluationBatch(batch_id="bat_" + execution_id[:48], results=(normalized,)))
        except QualityGateContractError:
            return needs("quality_contract_rejected")
        if normalized.module_status is ModuleResultStatus.BLOCKED:
            return needs("module_blocked", reasons=tuple(sorted(r.value for r in normalized.blocking_reasons)))
        manifest = evaluation.synthesis_manifest
        if not fully_accepted(output, manifest.accepted_result_ids, manifest.accepted_claim_ids):
            return needs("quality_rejected", (("revised_context_or_supported_request",),))
        return result(ResultKind.MODULE_RESULT, module_result=output)
