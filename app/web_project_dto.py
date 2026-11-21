from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, model_validator

from app.web_session_dto import DTO, OrganizationMembership, Versioned

Name = Annotated[str, Field(min_length=1, max_length=120)]
Text = Annotated[str, Field(max_length=4000)]
BrandName = Annotated[str, Field(max_length=255)]
Goal = Annotated[str, Field(min_length=1, max_length=300)]
Goals = Annotated[list[Goal], Field(max_length=10)]
Channels = Annotated[list[Annotated[str, Field(min_length=1, max_length=100)]], Field(max_length=20)]
Status = Literal["active", "draft", "archived"]
Color = Literal["teal", "violet", "coral", "amber", "blue", "green"]
Version = Annotated[int, Field(strict=True, ge=1)]


class BrandExtra(DTO):
    industry: Annotated[str, Field(max_length=200)] | None = None
    usp: Text | None = None
    competitors: Goals | None = None
    customer_job_or_need: Text | None = None
    relevant_alternative: Text | None = None
    product_truth: Text | None = None
    existing_proof: Text | None = None
    geography: Text | None = None
    economics: Text | None = None


class BrandFields(DTO):
    brand_name: BrandName | None = None
    product_description: Text | None = None
    audience: Text | None = None
    tone: Text | None = None
    goals: Goals | None = None
    channels: Channels | None = None
    extra: BrandExtra = Field(default_factory=BrandExtra)


class ProjectCreate(DTO):
    name: Name
    status: Literal["active", "draft"] = "active"
    color: Color | None = None
    brand: BrandFields = Field(default_factory=BrandFields)


class VersionPatch(DTO):
    expected_version: Version

    @model_validator(mode="after")
    def require_changes(self):
        if len(self.model_fields_set) < 2:
            raise ValueError("missing changes")
        return self


class ProjectPatch(VersionPatch):
    name: Name = Field(default=None)
    status: Status = Field(default=None)
    color: Color | None = None


class BrandPatch(BrandFields, VersionPatch):
    pass


class BrandImport(DTO):
    expected_version: Version
    confirm_overwrite: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def require_confirmation(self):
        if not self.confirm_overwrite:
            raise ValueError("confirmation required")
        return self


class UserRef(DTO):
    id: int
    display_name: BrandName | None
    is_self: bool


class Provenance(DTO):
    source: Literal["telegram_brand_profile"] = "telegram_brand_profile"
    imported_at: AwareDatetime
    imported_by: UserRef


class Brand(Versioned):
    project_id: UUID
    version: Version
    brand_name: BrandName | None
    product_description: Text | None
    audience: Text | None
    tone: Text | None
    goals: Goals
    channels: Channels
    extra: BrandExtra
    imported_from: Provenance | None
    updated_at: AwareDatetime
    updated_by: UserRef | None


class Permissions(DTO):
    can_edit: bool
    can_submit: bool
    can_import_telegram_brand: bool


class Project(Versioned):
    id: UUID
    org_id: UUID
    name: Name
    status: Status
    color: Color | None
    version: Version
    role: Literal["owner", "viewer", "editor"]
    permissions: Permissions
    created_by: UserRef
    created_at: AwareDatetime
    updated_at: AwareDatetime
    brand: Brand


class ProjectList(Versioned):
    items: list[Project]
    next_cursor: str | None


class OrgList(Versioned):
    items: list[OrganizationMembership] = Field(max_length=50)
