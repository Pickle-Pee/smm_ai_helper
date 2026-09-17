"""Explicit deterministic inventory; no dynamic import or model fallback."""
from types import MappingProxyType
from .lead_funnel import LeadFunnelCalculator


class DeterministicToolRegistry:
    def __init__(self, *, lead_funnel=None):
        self._tools = MappingProxyType({"lead_funnel_calculator_v1": lead_funnel or LeadFunnelCalculator()})

    def resolve(self, key):
        return self._tools[key]
