"""Bounded model wire schemas; technical identities are assigned by code."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class CompetitorStatement(OutputStatement):
    output_name: Literal[
        "competitor_set", "direct_competitors", "indirect_competitors", "substitutes",
        "observable_positioning", "offers", "proof", "strengths", "weaknesses", "patterns",
        "contradictions", "market_gaps", "differentiation_hypotheses.",
    ]


class PositioningStatement(OutputStatement):
    output_name: Literal[
        "category", "frame_of_reference", "target", "demand_context", "JTBD_frame",
        "value_proposition", "differentiation", "points_of_parity", "points_of_difference",
        "RTB", "positioning_statement", "USP_directions", "offer", "message_hierarchy",
        "claim_risks", "validation_plan.",
    ]


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
    outputs: list[PositioningStatement] = Field(min_length=1, max_length=32)


class TextPost(StrictOutput):
    headline: Annotated[str, Field(min_length=1, max_length=200)]
    body: Text
    cta: Annotated[str, Field(min_length=1, max_length=300)]


class CreatorOutput(OutputBase):
    post: TextPost
    outputs: list[CreatorStatement] = Field(min_length=1, max_length=22)
