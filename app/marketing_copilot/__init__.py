"""Non-executable copilot foundation; intentionally disconnected from runtime ingress."""
from .contracts import CopilotContractError, ExecutionDecision, ExecutionMode, IntentKind, MarketingIntent, ReasonCode
from .context_resolver import ContextEntry, ContextLayer, ContextResolver
from .execution_policy import ExecutionPolicy
from .interpreter import IntentModelCall, MarketingIntentInterpreter
from .orchestrator_adapter import OrchestratorAdapter

__all__ = [
    "CopilotContractError", "ExecutionDecision", "ExecutionMode", "IntentKind", "MarketingIntent", "ReasonCode",
    "ContextEntry", "ContextLayer", "ContextResolver", "ExecutionPolicy", "IntentModelCall",
    "MarketingIntentInterpreter", "OrchestratorAdapter",
]
