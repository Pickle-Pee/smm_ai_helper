"""Opt-in, saved case explanations; existing Copilot DTOs stay unchanged."""
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from .api_contracts import StrictDTO, Text


class MentorSection(StrictDTO):
    key: Literal["goal", "inputs", "principle", "rationale", "alternatives", "limitations", "verification", "takeaway"]
    title: Text
    paragraphs: list[Text] = Field(min_length=1, max_length=1024)


class MentorExplanation(StrictDTO):
    schema_version: Literal["case_mentor.v1"] = "case_mentor.v1"
    run_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    status: Literal["COMPLETED"] = "COMPLETED"
    sections: list[MentorSection] = Field(min_length=8, max_length=8)


class MentorQuestion(StrictDTO):
    request_key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class MentorAnswer(StrictDTO):
    schema_version: Literal["case_mentor_answer.v1"] = "case_mentor_answer.v1"
    run_id: str
    question: Text
    focus: Literal["alternative", "verification", "resources", "evidence", "overview"]
    paragraphs: list[Text] = Field(min_length=1, max_length=8192)


class CaseFeedback(StrictDTO):
    request_key: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")]
    outcome: Literal["applied", "hypothesis_tested", "worked", "did_not_work", "corrected"]
    notes: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    metrics: Annotated[str, StringConstraints(max_length=2000)] = ""


class SavedFeedback(StrictDTO):
    schema_version: Literal["case_feedback.v1"] = "case_feedback.v1"
    run_id: str
    outcome: Literal["applied", "hypothesis_tested", "worked", "did_not_work", "corrected"]
    notes: Text
    metrics: Text
    verification: Literal["user_reported"] = "user_reported"
