"""Validate fixed-workflow responses before any status or artifact is rendered."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.workflows.schemas import RESULT_TYPES, Step

RunID = Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
Status = Literal["needs_input", "queued", "running", "awaiting_creative", "awaiting_mentor", "completed", "failed"]


class WireModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class Evidence(WireModel):
    source_class: str
    provenance: str


class Image(WireModel):
    image_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]+$")]
    url: str

    @model_validator(mode="after")
    def matching_resource(self):
        if self.url != f"/images/{self.image_id}.png":
            raise ValueError("Invalid saved image resource")
        return self


class Artifact(WireModel):
    schema_version: Literal["marketing_artifact.v1"]
    run_id: RunID
    step: Step
    result: dict
    limitations: list[str]
    evidence: list[Evidence]
    images: list[Image]

    @model_validator(mode="after")
    def structured_result(self):
        RESULT_TYPES[self.step].model_validate(self.result, strict=True)
        return self


class Delivery(WireModel):
    id: str
    status: Literal["pending", "sending", "delivered", "failed"]
    part: Annotated[int, Field(ge=0)]


class WorkflowJobSummary(WireModel):
    job_id: str
    step: Step
    status: Literal["pending", "running", "succeeded", "failed"]
    error: str | None = None


class RunSummary(WireModel):
    run_id: RunID
    status: Status
    step: Step | None = None


class WorkflowResponse(WireModel):
    run_id: RunID
    status: Status
    current_step: Step | None
    error: str | None
    missing_fields: list[Literal["product", "audience", "goal"]]
    artifacts: dict[Step, Artifact]
    jobs: list[WorkflowJobSummary]
    delivery: list[Delivery]

    @model_validator(mode="after")
    def coherent_response(self):
        if self.status == "needs_input" and not self.missing_fields:
            raise ValueError("Missing clarification fields")
        required_artifact = {"awaiting_creative": "analysis", "awaiting_mentor": "creative", "completed": "mentor"}.get(self.status)
        if required_artifact and required_artifact not in self.artifacts:
            raise ValueError("Missing completed step artifact")
        if any(artifact.run_id != self.run_id or artifact.step != key for key, artifact in self.artifacts.items()):
            raise ValueError("Mismatched artifact identity")
        return self


def validate_workflow(data):
    """Return original wire data without coercion, or the shared safe client error."""
    from bot.backend import BackendError
    try:
        WorkflowResponse.model_validate(data)
    except ValidationError as exc:
        raise BackendError("Сервер вернул некорректный ответ. Проверьте /runs и повторите просмотр позже.") from exc
    return data


def validate_runs(data):
    from bot.backend import BackendError
    try:
        if not isinstance(data, list):
            raise ValueError("Expected workflow list")
        for row in data:
            RunSummary.model_validate(row)
    except (ValidationError, ValueError) as exc:
        raise BackendError("Сервер вернул некорректный список проектов. Повторите /runs позже.") from exc
    return data
