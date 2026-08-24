class MarketingOrchestratorError(ValueError):
    """Base error for deterministic planning contracts and validation."""


class InvalidInterpretationError(MarketingOrchestratorError):
    """The typed interpretation is absent, ambiguous, or unsupported."""


class InvalidContextValueError(MarketingOrchestratorError):
    """A caller-supplied context value is mutable or non-canonical."""


class UnknownModulePlanningError(MarketingOrchestratorError):
    """An explicit canonical module ID or alias is not registered."""


class InvalidPlanError(MarketingOrchestratorError):
    """A plan violates a structural or Registry compatibility invariant."""
