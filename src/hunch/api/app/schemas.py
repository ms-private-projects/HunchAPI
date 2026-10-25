"""Pydantic response models of the Hunch API."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class ProjectConfigurationResponse(BaseModel):
    api_version: str
    venues: list[str]
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


class TakeResource(BaseModel):
    """A take as the API and the Agent see it."""

    model_config = ConfigDict(extra="forbid")

    uid: str
    owner_user_uid: str
    title: str
    thesis_text: str
    constraints: dict[str, Any] | None = None
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


class TakeListResponse(BaseModel):
    items: list[TakeResource]
    limit: int
    offset: int
    returned: int


__all__ = [
    "DISCLAIMERS",
    "CapabilityCatalogResponse",
    "CapabilitySummary",
    "HealthResponse",
    "ProjectConfigurationResponse",
    "TakeListResponse",
    "TakeResource",
]
