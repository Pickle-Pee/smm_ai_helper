"""Resolve caller-authorized inputs directly into the existing PlanningContext."""
from dataclasses import dataclass
from enum import Enum
import re
from types import MappingProxyType

from app.marketing_orchestrator import AuthorizedContextFact, PlanningContext, UpstreamFinding
from app.module_registry import ToolCapability

from .contracts import CopilotContractError


class ContextLayer(str, Enum):
    CURRENT_REQUEST = "CURRENT_REQUEST"
    OWNED_SITE = "OWNED_SITE"
    PROJECT_RUN = "PROJECT_RUN"
    BRAND_PROFILE = "BRAND_PROFILE"
    CONVERSATION = "CONVERSATION"


@dataclass(frozen=True, slots=True)
class ContextEntry:
    """A semantic conflict key around an existing fact, not another context model.

    Sources must be caller-authorized before entry. Typed facts use the exact
    PlanningInputKey value as their semantic key; labels never imply equivalence.
    """

    semantic_key: str
    fact: AuthorizedContextFact

    def __post_init__(self):
        if (type(self.semantic_key) is not str or len(self.semantic_key) > 128
                or re.fullmatch(r"[a-z][a-z0-9_]*(?:[.:-][a-z0-9_]+)*", self.semantic_key) is None):
            raise CopilotContractError("Invalid semantic_key")
        if type(self.fact) is not AuthorizedContextFact or not self.fact.source:
            raise CopilotContractError("ContextEntry requires an existing fact with source provenance")
        if self.fact.input_key is not None and self.semantic_key != self.fact.input_key.value:
            raise CopilotContractError("semantic_key must match the typed input_key")


def has_value(value) -> bool:
    """Absent/empty values cannot satisfy structural context requirements; 0/False can."""
    if value is None:
        return False
    if type(value) is str:
        return bool(value.strip())
    if type(value) in (tuple, dict, MappingProxyType):
        return bool(value) and any(has_value(item) for item in (value.values() if isinstance(value, (dict, MappingProxyType)) else value))
    return True


def _thaw(value):
    # AuthorizedContextFact freezes JSON; its constructor intentionally does not
    # accept MappingProxyType input. Copy its values before reconstructing provenance.
    if type(value) is MappingProxyType:
        return {key: _thaw(item) for key, item in value.items()}
    if type(value) is tuple:
        return [_thaw(item) for item in value]
    return value


class ContextResolver:
    def resolve(
        self, *, current_request: tuple[ContextEntry, ...] = (),
        owned_site_context: tuple[ContextEntry, ...] = (),
        project_run: tuple[ContextEntry, ...] = (), brand_profile: tuple[ContextEntry, ...] = (),
        conversation: tuple[ContextEntry, ...] = (),
        authorized_upstream_findings: tuple[UpstreamFinding, ...] = (),
        assumptions: tuple[str, ...] = (), constraints: tuple[str, ...] = (),
        available_tools: frozenset[ToolCapability] = frozenset(),
    ) -> PlanningContext:
        layers = (
            (ContextLayer.CURRENT_REQUEST, current_request), (ContextLayer.OWNED_SITE, owned_site_context),
            (ContextLayer.PROJECT_RUN, project_run),
            (ContextLayer.BRAND_PROFILE, brand_profile), (ContextLayer.CONVERSATION, conversation),
        )
        selected: dict[str, tuple[ContextLayer, AuthorizedContextFact]] = {}
        for layer, entries in layers:
            if type(entries) is not tuple or len(entries) > 128 or any(type(e) is not ContextEntry for e in entries):
                raise CopilotContractError("Context sources require at most 128 typed entries per layer")
            keys = [entry.semantic_key for entry in entries]
            if len(set(keys)) != len(keys):
                raise CopilotContractError("Duplicate semantic_key within a context layer")
            for entry in entries:
                if layer is ContextLayer.OWNED_SITE:
                    # Acquisition is descriptive context, never a shortcut around
                    # the existing verified product truth / proof input slots.
                    input_key = entry.fact.input_key.value if entry.fact.input_key else entry.fact.label
                    if {entry.semantic_key, input_key} & {"product_truth", "existing_proof"} or (
                        not isinstance(entry.fact.value, MappingProxyType)
                        or entry.fact.value.get("trust") != "site_claim"
                    ):
                        raise CopilotContractError("Owned-site entries must remain marked site claims, not product truth")
                if entry.fact.authorized:
                    selected.setdefault(entry.semantic_key, (layer, entry.fact))
        project, known = [], []
        for _, (layer, fact) in sorted(selected.items()):
            # Explicit empty current values mask stale lower-priority facts. They
            # are omitted, so the existing planner cannot count them as known inputs.
            if not has_value(fact.value):
                continue
            copied = AuthorizedContextFact(
                fact_id=fact.fact_id, label=fact.label, value=_thaw(fact.value), input_key=fact.input_key,
                module_relevance=fact.module_relevance, scenario_relevance=fact.scenario_relevance,
                source=f"{layer.value}:{fact.source}", evidence=fact.evidence, confidence=fact.confidence,
                sensitivity=fact.sensitivity, authorized=fact.authorized,
            )
            (project if layer in {ContextLayer.CURRENT_REQUEST, ContextLayer.OWNED_SITE, ContextLayer.PROJECT_RUN} else known).append(copied)
        if (type(authorized_upstream_findings) is not tuple or len(authorized_upstream_findings) > 128
                or any(type(f) is not UpstreamFinding for f in authorized_upstream_findings)):
            raise CopilotContractError("Upstream inputs must be caller-authorized UpstreamFinding records")
        identities = [(f.producer_node_id, f.key) for f in authorized_upstream_findings]
        if len(set(identities)) != len(identities):
            raise CopilotContractError("Duplicate upstream finding identity")
        return PlanningContext(
            project_context=tuple(sorted(project, key=lambda f: f.fact_id)),
            known_facts=tuple(sorted(known, key=lambda f: f.fact_id)),
            upstream_findings=tuple(sorted(authorized_upstream_findings, key=lambda f: (f.producer_node_id, f.key))),
            assumptions=assumptions, constraints=constraints, available_tools=available_tools,
        )

    @staticmethod
    def artifact_reference(*, producer_node_id: str, artifact_id: str) -> UpstreamFinding:
        """Represent an already-authorized saved artifact; never promote it to a fact.

        The caller owns artifact lookup/ownership checks. This helper does no I/O.
        """
        if type(artifact_id) is not str or not artifact_id.strip() or len(artifact_id) > 2048:
            raise CopilotContractError("Invalid artifact reference")
        return UpstreamFinding(producer_node_id, "artifact.reference", {"artifact_id": artifact_id})
