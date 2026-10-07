"""Bounded model wire schemas; technical identities are assigned by code."""
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Text = Annotated[str, Field(min_length=1, max_length=4000)]
Reference = Annotated[str, Field(min_length=1, max_length=128)]


class StrictOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True,
                              hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def valid_text(cls, value):
        if isinstance(value, str):
            value.encode("utf-8")
            if not value.strip() or "\x00" in value:
                raise ValueError("Invalid output text")
        return value


class OutputStatement(StrictOutput):
    """Wire fields mapped directly to the existing NormalizedClaim contract."""
    output_name: Reference
    text: Text
    kind: Literal["OBSERVATION", "INFERENCE", "HYPOTHESIS", "RECOMMENDATION"]
    confidence: Literal["UNKNOWN", "LOW", "MEDIUM", "HIGH"]
    evidence_ids: list[Reference] = Field(max_length=32)
    parent_claim_ids: list[Reference] = Field(max_length=32)

    @model_validator(mode="after")
    def require_support(self):
        if not self.evidence_ids and not self.parent_claim_ids:
            raise ValueError("Statement support is required")
        return self

    @classmethod
    def __get_pydantic_json_schema__(cls, core_schema, handler):
        # Pydantic's model validator cannot emit this cross-field OR. Keep its
        # wire representation here so every derived statement (including its
        # narrower output-name/kind fields) inherits the same support floor.
        schema = handler.resolve_ref_schema(handler(core_schema))
        alternatives = []
        for support_field in ("evidence_ids", "parent_claim_ids"):
            branch = deepcopy(schema)
            branch.pop("title", None)
            branch["properties"][support_field]["minItems"] = 1
            alternatives.append(branch)
        # Each anyOf branch is a complete strict object: all fields required,
        # no extra properties, bounded arrays. Both-nonempty matches both.
        schema["anyOf"] = alternatives
        return schema


class CompetitorStatement(OutputStatement):
    output_name: Literal[
        "competitor_set", "direct_competitors", "indirect_competitors", "substitutes",
        "observable_positioning", "offers", "proof", "strengths", "weaknesses", "patterns",
        "contradictions", "market_gaps", "differentiation_hypotheses.",
    ]


class PositioningStatement(OutputStatement):
    output_name: Literal[
        "category", "frame_of_reference", "target", "demand_context", "JTBD_frame",
        "value_proposition", "points_of_parity",
        "RTB", "positioning_statement", "offer", "message_hierarchy",
        "claim_risks", "validation_plan.",
    ]


class PositioningHypothesisStatement(OutputStatement):
    # Disjoint output names make the kind rule enforceable by strict generation.
    output_name: Literal["differentiation", "points_of_difference", "USP_directions"]
    kind: Literal["HYPOTHESIS"]


class PositioningCoreStatement(OutputStatement):
    output_name: Literal[
        "target", "value_proposition", "RTB", "positioning_statement", "offer",
        "message_hierarchy", "claim_risks", "validation_plan.",
    ]


class PositioningJobStatement(OutputStatement):
    output_name: Literal["JTBD_frame", "demand_context"]


class PositioningJobHypothesisStatement(PositioningJobStatement):
    kind: Literal["HYPOTHESIS"]


class PositioningAlternativeStatement(OutputStatement):
    output_name: Literal["category", "frame_of_reference", "points_of_parity"]


class PositioningAlternativeHypothesisStatement(PositioningAlternativeStatement):
    kind: Literal["HYPOTHESIS"]


class CreatorStatement(OutputStatement):
    output_name: Literal[
        "creative_strategy", "distinct_angles", "concepts", "hooks", "scripts", "banner_copy",
        "visual_briefs", "image_prompts", "CTA", "test_variations", "creative_hypotheses.",
    ]


class OutputBase(StrictOutput):
    assumptions: list[Text] = Field(max_length=12)
    limitations: list[Text] = Field(max_length=12)


class CompetitorOutput(OutputBase):
    outputs: list[CompetitorStatement] = Field(min_length=1, max_length=26)


class PositioningOutput(OutputBase):
    outputs: list[PositioningStatement | PositioningHypothesisStatement] = Field(min_length=1, max_length=32)


class PositioningWithoutJobOutput(OutputBase):
    outputs: list[PositioningCoreStatement | PositioningJobHypothesisStatement
                  | PositioningAlternativeStatement | PositioningHypothesisStatement] = Field(min_length=1, max_length=32)


class PositioningWithoutAlternativeOutput(OutputBase):
    outputs: list[PositioningCoreStatement | PositioningJobStatement
                  | PositioningAlternativeHypothesisStatement | PositioningHypothesisStatement] = Field(min_length=1, max_length=32)


class PositioningWithoutSeedsOutput(OutputBase):
    outputs: list[PositioningCoreStatement | PositioningJobHypothesisStatement
                  | PositioningAlternativeHypothesisStatement | PositioningHypothesisStatement] = Field(min_length=1, max_length=32)


class TextPost(StrictOutput):
    headline: Annotated[str, Field(min_length=1, max_length=200)]
    body: Text
    cta: Annotated[str, Field(min_length=1, max_length=300)]


class CreatorOutput(OutputBase):
    post: TextPost
    outputs: list[CreatorStatement] = Field(min_length=1, max_length=22)
