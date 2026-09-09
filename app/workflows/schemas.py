from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.safe_http import validate_url

Step = Literal["analysis", "creative", "mentor"]
Text = Annotated[str, Field(min_length=1, max_length=4000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="after")
    @classmethod
    def postgres_text(cls, value):
        if isinstance(value, list):
            for item in value:
                cls.postgres_text(item)
        if isinstance(value, str):
            value.encode("utf-8")
            if "\x00" in value:
                raise ValueError("NUL is not valid PostgreSQL text")
        return value


class BusinessInput(StrictModel):
    product: str = Field(default="", max_length=4000)
    audience: str = Field(default="", max_length=2000)
    goal: str = Field(default="", max_length=1000)


class StartRequest(BusinessInput):
    schema_version: Literal["marketing_request.v1"] = "marketing_request.v1"
    request_key: str = Field(min_length=1, max_length=128)
    competitor_url: str = Field(min_length=1, max_length=2048)

    @field_validator("competitor_url")
    @classmethod
    def public_url(cls, value):
        validate_url(value)
        return value


class ContinueRequest(StrictModel):
    action: Literal["creative", "mentor"]


class Claim(StrictModel):
    text: Text
    output_name: str = Field(min_length=1, max_length=128)
    kind: Literal["OBSERVATION", "INFERENCE", "HYPOTHESIS", "ASSUMPTION", "RECOMMENDATION"]
    confidence: Literal["LOW", "MEDIUM", "UNKNOWN"]
    evidence_ids: list[str] = Field(max_length=12)
    parent_claim_ids: list[str] = Field(max_length=12)


class ResultBase(StrictModel):
    claims: list[Claim] = Field(min_length=1, max_length=12)
    assumptions: list[Text] = Field(max_length=10)
    limitations: list[Text] = Field(max_length=10)


class AnalysisResult(ResultBase):
    schema_version: Literal["competitor_analysis.v1"]
    observed_positioning: Text
    strengths: list[Text] = Field(min_length=1, max_length=6)
    weaknesses: list[Text] = Field(min_length=1, max_length=6)
    customer_hypotheses: list[Text] = Field(min_length=1, max_length=6)
    differentiation: list[Text] = Field(min_length=1, max_length=6)
    practical_brief: Text


class Scene(StrictModel):
    start_seconds: int = Field(ge=0, le=120)
    end_seconds: int = Field(ge=1, le=120)
    visual: Text
    narration: Text
    retention_hook: Text


class CreativeResult(ResultBase):
    schema_version: Literal["creative_package.v1"]
    hypothesis: Text
    trigger: Text
    offer: Text
    headline: str = Field(min_length=1, max_length=100)
    cta: str = Field(min_length=1, max_length=80)
    image_brief: Text
    scenes: list[Scene] = Field(min_length=3, max_length=8)

    @model_validator(mode="after")
    def valid_timeline(self):
        previous = 0
        for scene in self.scenes:
            if scene.start_seconds != previous or scene.end_seconds <= scene.start_seconds:
                raise ValueError("Scenes must form a contiguous positive timeline starting at zero")
            previous = scene.end_seconds
        if not 15 <= previous <= 60:
            raise ValueError("Short video duration must be between 15 and 60 seconds")
        return self


class MentorResult(ResultBase):
    schema_version: Literal["mentor_explanation.v1"]
    principle: Text
    evidence_explanation: Text
    alternative: Text
    when_it_fails: list[Text] = Field(min_length=1, max_length=6)
    validation_plan: list[Text] = Field(min_length=1, max_length=6)


class AnalysisInput(StrictModel):
    schema_version: Literal["analysis_input.v1"] = "analysis_input.v1"
    snapshot: dict
    sources: list[dict]


class CreativeInput(StrictModel):
    schema_version: Literal["creative_input.v1"] = "creative_input.v1"
    snapshot: dict
    analysis: dict


class MentorInput(StrictModel):
    schema_version: Literal["mentor_input.v1"] = "mentor_input.v1"
    snapshot: dict
    analysis: dict
    creative: dict


RESULT_TYPES = {"analysis": AnalysisResult, "creative": CreativeResult, "mentor": MentorResult}
