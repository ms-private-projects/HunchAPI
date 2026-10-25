"""Pydantic request and response models of the Hunch API."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from hunch.takes.services import TakeConstraints, TakeCreate, TakeUpdate
from msm.api.http import ResourceCollection as MarketsResourceCollection
from msm.api.http import ResourceDiscovery, ResourcePageInfo

DISCLAIMERS: tuple[str, ...] = (
    "Hunch is not a registered investment adviser and nothing it shows is investment advice.",
    "The person gives the instructions; Hunch builds, monitors and, when authorised, executes.",
    "Investing involves risk, including the loss of principal. Past performance does not predict "
    "future results.",
    "Returns are measured from each take's activation; practice takes show simulated results and "
    "no money was invested in them.",
)


class HealthResponse(BaseModel):
    status: Literal["ok"]


class CapabilitySummary(BaseModel):
    key: str
    name: str
    purpose: str
    contents: list[str]
    actions: list[str]
    surfaces: list[str]
    availability: Literal["available", "partial"]


class CapabilityCatalogResponse(BaseModel):
    capabilities: list[CapabilitySummary]


class AssistantRuntime(BaseModel):
    """Where the site's conversation with the Hunch Agent runs, as the CRM site expects it."""

    mode: Literal["local", "platform"]
    base_path: str | None = Field(
        default=None, description="Same-origin path of the local Tau proxy, local mode only."
    )


class AssistantConfiguration(BaseModel):
    enabled: bool
    runtime: AssistantRuntime | None = None
    agent_uid: str | None = None
    environment_uid: str | None = None
    display_name: str = "Hunch Agent"


class ProjectConfigurationResponse(BaseModel):
    api_version: str
    venues: list[str]
    assistant: AssistantConfiguration = Field(
        default_factory=lambda: AssistantConfiguration(enabled=False)
    )
    organization_environment_uid: str | None = None
    agent_uid: str | None = Field(
        default=None,
        description=(
            "This branch's deployed Hunch Agent, found when the request arrives; null when it is "
            "not available. When set, organization_environment_uid is that Agent's Environment."
        ),
    )
    request_user_uid: str | None = None
    disclaimers: list[str] = Field(default_factory=lambda: list(DISCLAIMERS))


# Profiles ---------------------------------------------------------------------------------------


class ProfileResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_uid: str
    handle: str
    display_name: str | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: str | None = Field(default=None, min_length=3, max_length=32)
    display_name: str | None = Field(default=None, max_length=255)


# Takes ------------------------------------------------------------------------------------------


class TakeResource(BaseModel):
    """A take as the API and the Agent see it."""

    model_config = ConfigDict(extra="forbid")

    uid: str
    owner_user_uid: str
    owner_handle: str | None = None
    title: str
    thesis_text: str
    constraints: TakeConstraints
    status: str
    execution_mode: str
    visibility: str
    forked_from_take_uid: str | None = None
    origin_take_uid: str | None = None
    signal_uid: str | None = None
    activated_at: dt.datetime | None = None
    published_at: dt.datetime | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class PageInfo(ResourcePageInfo):
    """Hunch schema name for the shared collection page contract."""


class ResourceCollection(MarketsResourceCollection[dict[str, Any]]):
    """Hunch schema name for the shared resource collection contract."""

    page_info: PageInfo = Field(alias="pageInfo")


class ResourceDiscoveryResponse(ResourceDiscovery):
    """Hunch schema name for the shared resource discovery contract."""


class TakeCreateRequest(TakeCreate):
    """Create a take for the acting user."""


class TakeUpdateRequest(TakeUpdate):
    """Edit the title, thesis or constraints of an owned take."""


class ExecutionModeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution_mode: Literal["practice", "approval", "autopilot"]


class ArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: str = Field(min_length=1, description="Exactly: DELETE <take uid>")


__all__ = [
    "DISCLAIMERS",
    "ArchiveRequest",
    "AssistantConfiguration",
    "AssistantRuntime",
    "CapabilityCatalogResponse",
    "CapabilitySummary",
    "ExecutionModeRequest",
    "HealthResponse",
    "PageInfo",
    "ProfileResource",
    "ProfileUpdateRequest",
    "ProjectConfigurationResponse",
    "ResourceCollection",
    "ResourceDiscoveryResponse",
    "TakeCreateRequest",
    "TakeResource",
    "TakeUpdateRequest",
]
