"""Deterministic, planning-only Marketing Orchestrator foundation."""

from .contracts import (
    AuthorizedContextFact,
    BlockingQuestion,
    ContextPacket,
    DataSufficiency,
    ExecutionReadiness,
    GraphDependency,
    InputClassification,
    PlanningInputKey,
    PlanningInputRequirement,
    OrchestrationPlan,
    PlanNode,
    PlanningContext,
    PlanningStatus,
    PlanningStopCondition,
    RequestInterpretation,
    Sensitivity,
    StructuralValidity,
    UpstreamFinding,
)
from .errors import (
    InvalidInterpretationError,
    InvalidContextValueError,
    InvalidPlanError,
    MarketingOrchestratorError,
    UnknownModulePlanningError,
)
from .planner import MarketingOrchestratorPlanner
from .validation import PlanValidator

__all__ = [
    "AuthorizedContextFact",
    "BlockingQuestion",
    "ContextPacket",
    "DataSufficiency",
    "ExecutionReadiness",
    "GraphDependency",
    "InputClassification",
    "PlanningInputKey",
    "PlanningInputRequirement",
    "InvalidContextValueError",
    "InvalidInterpretationError",
    "InvalidPlanError",
    "MarketingOrchestratorError",
    "MarketingOrchestratorPlanner",
    "OrchestrationPlan",
    "PlanNode",
    "PlanValidator",
    "PlanningContext",
    "PlanningStatus",
    "PlanningStopCondition",
    "RequestInterpretation",
    "Sensitivity",
    "StructuralValidity",
    "UnknownModulePlanningError",
    "UpstreamFinding",
]
