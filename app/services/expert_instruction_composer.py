from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Callable

from app.prompts.expert_core import (
    EXPERT_CORE_VERSION,
    load_expert_core,
    validate_expert_core,
)


EXPERT_CORE_START_PREFIX = "<!-- EXPERT_CORE:"
EXPERT_CORE_END = "<!-- /EXPERT_CORE -->"
SPECIALIZED_MODULE_START = "<!-- SPECIALIZED_MODULE -->"
SPECIALIZED_MODULE_END = "<!-- /SPECIALIZED_MODULE -->"
RESPONSE_MODE_START = "<!-- RESPONSE_MODE -->"
RESPONSE_MODE_END = "<!-- /RESPONSE_MODE -->"

_RESERVED_MARKERS = (
    EXPERT_CORE_START_PREFIX,
    EXPERT_CORE_END,
    SPECIALIZED_MODULE_START,
    SPECIALIZED_MODULE_END,
    RESPONSE_MODE_START,
    RESPONSE_MODE_END,
)
_SEMANTIC_VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")

_PRECEDENCE = """APPLICATION INSTRUCTION PRECEDENCE
1. EXPERT CORE non-negotiable evidence, safety, currentness, ethics, and no-fabrication rules take precedence over conflicting lower components.
2. SPECIALIZED MODULE instructions control task-specific method, deliverables, and presentation when they do not conflict with EXPERT CORE.
3. RESPONSE MODE instructions control request-specific output structure when they do not conflict with higher-precedence rules.
Later components do not weaken or override higher-precedence non-negotiable rules."""


class ExpertInstructionCompositionError(RuntimeError):
    """Raised before a model call when Expert Core cannot be composed safely."""


@dataclass(frozen=True)
class ComposedInstructions:
    rendered_text: str
    expert_core_version: str
    component_identities: tuple[str, ...]


class ExpertInstructionComposer:
    def __init__(
        self,
        core_loader: Callable[[str], str] = load_expert_core,
        version: str = EXPERT_CORE_VERSION,
    ) -> None:
        self._core_loader = core_loader
        self._version = version

    def compose(
        self,
        specialized_instructions: str | ComposedInstructions,
        response_mode_instructions: str | None = None,
    ) -> ComposedInstructions:
        if not _SEMANTIC_VERSION_PATTERN.fullmatch(self._version):
            raise ExpertInstructionCompositionError(
                f"Invalid Expert Core version: {self._version!r}"
            )

        if isinstance(specialized_instructions, ComposedInstructions):
            if response_mode_instructions is not None:
                raise ExpertInstructionCompositionError(
                    "Response-mode instructions cannot be added after composition"
                )
            self._validate_composed(specialized_instructions)
            return specialized_instructions

        specialized = self._validate_raw_component(
            specialized_instructions,
            component_name="specialized module",
        )
        response_mode = None
        if response_mode_instructions is not None:
            response_mode = self._validate_raw_component(
                response_mode_instructions,
                component_name="response mode",
            )

        try:
            core = self._core_loader(self._version)
        except Exception as exc:
            if isinstance(exc, ExpertInstructionCompositionError):
                raise
            raise ExpertInstructionCompositionError(
                f"Unable to load Expert Core version {self._version}"
            ) from exc

        try:
            core = validate_expert_core(core, self._version)
        except Exception as exc:
            raise ExpertInstructionCompositionError(
                f"Invalid Expert Core version {self._version}"
            ) from exc
        core = self._validate_raw_component(core, component_name="Expert Core")
        expert_core_start = f"{EXPERT_CORE_START_PREFIX}{self._version} -->"
        parts = [
            expert_core_start,
            _PRECEDENCE,
            "",
            core,
            EXPERT_CORE_END,
            "",
            SPECIALIZED_MODULE_START,
            specialized,
            SPECIALIZED_MODULE_END,
        ]
        identities = [
            f"expert_core:{self._version}",
            "specialized_module",
        ]

        if response_mode is not None:
            parts.extend(
                [
                    "",
                    RESPONSE_MODE_START,
                    response_mode,
                    RESPONSE_MODE_END,
                ]
            )
            identities.append("response_mode")

        result = ComposedInstructions(
            rendered_text="\n".join(parts),
            expert_core_version=self._version,
            component_identities=tuple(identities),
        )
        self._validate_composed(result)
        return result

    @staticmethod
    def _validate_raw_component(value: str, component_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ExpertInstructionCompositionError(
                f"{component_name} instructions must be non-empty text"
            )
        if any(marker in value for marker in _RESERVED_MARKERS):
            raise ExpertInstructionCompositionError(
                f"{component_name} instructions contain a reserved marker"
            )
        return value.strip()

    def _validate_composed(self, value: ComposedInstructions) -> None:
        expected_core_identity = f"expert_core:{self._version}"
        expected_identities = (
            (expected_core_identity, "specialized_module"),
            (expected_core_identity, "specialized_module", "response_mode"),
        )
        if value.expert_core_version != self._version:
            raise ExpertInstructionCompositionError(
                "Composed instructions use a different Expert Core version"
            )
        if value.component_identities not in expected_identities:
            raise ExpertInstructionCompositionError(
                "Composed instruction component order is invalid"
            )

        expert_core_start = f"{EXPERT_CORE_START_PREFIX}{self._version} -->"
        if value.rendered_text.count(EXPERT_CORE_START_PREFIX) != 1:
            raise ExpertInstructionCompositionError(
                "Composed instructions must contain exactly one Expert Core start marker"
            )
        if value.rendered_text.count(EXPERT_CORE_END) != 1:
            raise ExpertInstructionCompositionError(
                "Composed instructions must contain exactly one Expert Core end marker"
            )
        if not value.rendered_text.startswith(expert_core_start):
            raise ExpertInstructionCompositionError(
                "Expert Core must be the first composed component"
            )

        marker_counts = {
            SPECIALIZED_MODULE_START: 1,
            SPECIALIZED_MODULE_END: 1,
            RESPONSE_MODE_START: (
                1 if "response_mode" in value.component_identities else 0
            ),
            RESPONSE_MODE_END: (
                1 if "response_mode" in value.component_identities else 0
            ),
        }
        for marker, expected_count in marker_counts.items():
            if value.rendered_text.count(marker) != expected_count:
                raise ExpertInstructionCompositionError(
                    "Composed instruction component boundaries are invalid"
                )

        ordered_markers = [
            expert_core_start,
            EXPERT_CORE_END,
            SPECIALIZED_MODULE_START,
            SPECIALIZED_MODULE_END,
        ]
        if "response_mode" in value.component_identities:
            ordered_markers.extend([RESPONSE_MODE_START, RESPONSE_MODE_END])
        positions = [value.rendered_text.index(marker) for marker in ordered_markers]
        if positions != sorted(positions):
            raise ExpertInstructionCompositionError(
                "Composed instruction component order is invalid"
            )


__all__ = [
    "ComposedInstructions",
    "EXPERT_CORE_END",
    "EXPERT_CORE_START_PREFIX",
    "ExpertInstructionComposer",
    "ExpertInstructionCompositionError",
    "RESPONSE_MODE_END",
    "RESPONSE_MODE_START",
    "SPECIALIZED_MODULE_END",
    "SPECIALIZED_MODULE_START",
]
