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


class ResearchConfiguration(BaseModel):
    mode: str = Field(description="`inference` records a model call; `heuristic` matches themes.")
    build_execution: str = Field(
        description="`inline` in the API process or `job` on the platform."
    )
    bars_provider: str
    inference_provider: str | None = None
    inference_model: str | None = None


class ConnectorConfiguration(BaseModel):
    mode: str = Field(
        description="`live` calls the venue connectors; `simulated` is a local paper venue."
    )
    venues: dict[str, bool] = Field(
        default_factory=dict,
        description="Per venue: whether a connector is configured in this mode.",
    )


class ProjectConfigurationResponse(BaseModel):
    api_version: str
    venues: list[str]
    research: ResearchConfiguration
    connectors: ConnectorConfiguration = Field(
        default_factory=lambda: ConnectorConfiguration(mode="live")
    )
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
    email_digest: bool = Field(default=False, description="Daily email digest opted in.")
    email_address: str | None = Field(
        default=None, description="Digest address; null means the platform user's email."
    )
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None


class ProfileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: str | None = Field(default=None, min_length=3, max_length=32)
    display_name: str | None = Field(default=None, max_length=255)
    email_digest: bool | None = None
    email_address: str | None = Field(default=None, max_length=255)


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


# Building, revisions, weights, performance ------------------------------------------------------


class BuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_mode: Literal["inference", "heuristic"] | None = Field(
        default=None, description="Override the configured research mode for this build."
    )


class RevisionResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uid: str
    take_uid: str
    revision: int
    kind: str
    rationale_md: str
    weights: list[dict[str, Any]]
    cash_weight: float | None = None
    guardrail_notes: list[str] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Numbered evidence items (id, ticker, kind, title, summary, source, url, "
        "published_at) the rationale and candidates cite.",
    )
    created_by: str
    inference_request_uids: list[str] = Field(default_factory=list)
    signal_time_index: dt.datetime | None = None
    created_at: dt.datetime | None = None


class BuildResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    execution: Literal["inline", "job"]
    take: TakeResource
    revision: RevisionResource | None = None
    job_run_uid: str | None = Field(
        default=None, description="The JobRun to poll when the build runs as a platform Job."
    )


class WeightsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    take_uid: str
    as_of: dt.datetime | str | None = None
    items: list[dict[str, Any]]
    invested: float
    cash: float


class InstrumentResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    figi: str
    ticker: str
    name: str
    exchange_code: str | None = None
    security_type: str | None = None
    sector: str | None = None
    themes: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    is_tradable: bool = True


class JobRunResource(BaseModel):
    model_config = ConfigDict(extra="allow")

    uid: str
    status: str | None = None


# Linked accounts, funding and execution ---------------------------------------------------------


class LinkedAccountResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uid: str
    venue: str
    account_uid: str
    account_identifier: str | None = None
    account_name: str | None = None
    is_paper: bool = True
    status: str
    ownership_verified: bool = True
    simulated: bool = False
    currency: str = "USD"
    equity: float | None = None
    cash: float | None = None
    linked_at: dt.datetime | None = None
    revoked_at: dt.datetime | None = None


class LinkAccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    venue: Literal["alpaca", "ibkr"]
    account_uid: str | None = Field(
        default=None,
        description=(
            "The connector's Account uid to link. Omit it in simulated mode to create a paper "
            "account, or when exactly one registered account belongs to you."
        ),
    )
    account_name: str | None = Field(default=None, max_length=255)


class HoldingResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_identifier: str
    kind: str
    quantity: float
    direction: int
    symbol: str | None = None
    figi: str | None = None
    market_value: float | None = None


class HoldingsSnapshotResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_uid: str
    time_index: dt.datetime
    holdings_set_uid: str | None = None
    cash: float
    holdings: list[HoldingResource]


class AutopilotPolicyResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_turnover_per_day: float = 0.25
    max_notional_per_order: float = 25_000.0
    max_single_name_weight: float = 0.20
    allow_new_instruments: bool = True
    trading_window: Literal["session", "any"] = "any"


class FundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_account_uid: str
    target_notional: float = Field(ge=100.0, le=50_000_000.0)
    execution_mode: Literal["approval", "autopilot"] = "approval"
    autopilot_policy: AutopilotPolicyResource | None = None


class FundPositionResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    figi: str
    ticker: str | None = None
    quantity: float
    price: float | None = None
    value: float
    weight: float | None = None


class FundingResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uid: str
    take_uid: str
    take_title: str | None = None
    profile_account_uid: str
    venue: str
    status: str
    target_notional: float
    currency: str
    execution_mode: str | None = None
    autopilot_policy: AutopilotPolicyResource | None = None
    execution_capability: str | None = None
    nav: float | None = None
    cash: float | None = None
    invested: float | None = None
    return_on_notional: float | None = None
    as_of: dt.datetime | None = None
    positions: list[FundPositionResource] = Field(default_factory=list)
    created_at: dt.datetime | None = None
    activated_at: dt.datetime | None = None
    closed_at: dt.datetime | None = None


class ProposalLegResource(BaseModel):
    model_config = ConfigDict(extra="allow")

    client_order_id: str
    figi: str
    ticker: str | None = None
    side: str
    quantity: float
    estimated_price: float | None = None
    estimated_notional: float | None = None
    target_weight: float | None = None
    current_weight: float | None = None
    reason: str | None = None


class ProposalResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uid: str
    take_uid: str
    take_title: str | None = None
    funding_uid: str
    trigger: str
    status: str
    legs: list[ProposalLegResource]
    summary_md: str
    estimated_turnover: float | None = None
    autopilot_check: dict[str, Any] | None = None
    manual_execution: bool = False
    expires_at: dt.datetime | None = None
    decided_at: dt.datetime | None = None
    submitted_at: dt.datetime | None = None
    completed_at: dt.datetime | None = None
    created_at: dt.datetime | None = None
    orders: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ProposalDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class FundResponse(BaseModel):
    funding: FundingResource
    proposal: ProposalResource


# Reviews, leaderboard, notifications -----------------------------------------------------------


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    research_mode: Literal["inference", "heuristic"] | None = None


class ReviewResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uid: str
    take_uid: str
    review_date: dt.date
    outcome: str
    verdict: str | None = None
    drift: dict[str, Any] | None = None
    thesis_check: dict[str, Any] | None = None
    proposal_uid: str | None = None
    summary_md: str
    created_at: dt.datetime | None = None


class LeaderboardEntryResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rank: int
    take_uid: str
    title: str | None = None
    owner_handle: str | None = None
    return_since_activation: float
    days_active: int
    value_points: int = 0
    is_simulated: bool = True
    is_funded: bool = False
    origin_take_uid: str | None = None
    metrics: dict[str, Any] | None = Field(
        default=None,
        description="total_return, annualised_return, annualised_volatility, sharpe_ratio, "
        "max_drawdown, best_day, worst_day, sessions (null until two sessions).",
    )


class LeaderboardResponse(BaseModel):
    snapshot_date: dt.date
    live: bool = Field(description="True when computed on request because no snapshot exists yet.")
    entries: list[LeaderboardEntryResource]
    disclaimers: list[str] = Field(default_factory=lambda: list(DISCLAIMERS))


class NotificationResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uid: str
    kind: str
    title: str
    body_md: str = ""
    take_uid: str | None = None
    payload: dict[str, Any] | None = None
    created_at: dt.datetime | None = None
    read_at: dt.datetime | None = None


class NotificationsResponse(BaseModel):
    items: list[NotificationResource]
    unread: int


class MarkReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uids: list[str] | None = Field(
        default=None, description="Omit to mark every notification read."
    )


__all__ = [
    "AutopilotPolicyResource",
    "ConnectorConfiguration",
    "DISCLAIMERS",
    "FundPositionResource",
    "FundRequest",
    "FundResponse",
    "FundingResource",
    "HoldingResource",
    "HoldingsSnapshotResource",
    "LeaderboardEntryResource",
    "LeaderboardResponse",
    "LinkAccountRequest",
    "LinkedAccountResource",
    "MarkReadRequest",
    "NotificationResource",
    "NotificationsResponse",
    "ProposalDecisionRequest",
    "ProposalLegResource",
    "ProposalResource",
    "ReviewRequest",
    "ReviewResource",
    "ArchiveRequest",
    "BuildRequest",
    "BuildResponse",
    "InstrumentResource",
    "JobRunResource",
    "RevisionResource",
    "WeightsResponse",
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
