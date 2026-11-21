"""Public projections pinned to brenvio web OpenAPI db1135f."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_serialization_defaults_required=True)


class Versioned(DTO):
    schema_version: Literal["web_api.v2"] = "web_api.v2"


class TelegramExchangeRequest(DTO):
    token: str = Field(min_length=32, max_length=256, pattern=r"^[A-Za-z0-9_-]+$", repr=False)


class TelegramBrowserChallenge(Versioned):
    confirmation_code: str = Field(pattern=r"^[A-Za-z0-9_-]{22}$", repr=False)
    expires_at: AwareDatetime


class CsrfToken(Versioned):
    csrf_token: str = Field(min_length=32, max_length=256, pattern=r"^[A-Za-z0-9_-]+$", repr=False)


class User(DTO):
    id: int = Field(ge=1)
    display_name: Annotated[str, Field(max_length=255)] | None
    created_at: AwareDatetime


class Identity(DTO):
    provider: Literal["telegram", "email", "oidc"]
    linked_at: AwareDatetime


class Organization(DTO):
    id: UUID
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["personal", "team"]
    created_at: AwareDatetime


class OrganizationMembership(DTO):
    organization: Organization
    role: Literal["owner", "editor", "viewer"]
    joined_at: AwareDatetime


class SessionInfo(DTO):
    issued_at: AwareDatetime
    idle_expires_at: AwareDatetime
    absolute_expires_at: AwareDatetime


class Features(DTO):
    copilot_requests: bool = False
    mentor: bool = False
    telegram_history: bool = False
    web_chat: bool = False
    team_organizations: bool = False
    email_login: bool = False
    brand_reimport: bool = False
    documents: bool = False


class Me(Versioned):
    user: User
    identities: list[Identity] = Field(max_length=8)
    memberships: list[OrganizationMembership] = Field(max_length=50)
    session: SessionInfo
    features: Features


class AuthSession(CsrfToken):
    me: Me
