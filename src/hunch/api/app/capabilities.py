"""Catalog of the capabilities this repository implements today.

The catalog describes existing behaviour only, so the site, the Agent and people can see what is
available without reading code. A capability is `partial` while its tables exist but its actions
are not yet exposed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

CapabilityAvailability = Literal["available", "partial"]


@dataclass(frozen=True, slots=True)
class Capability:
    """One user-facing repository capability and its current supported behaviour."""

    key: str
    name: str
    purpose: str
    contents: tuple[str, ...]
    actions: tuple[str, ...]
    surfaces: tuple[str, ...]
    availability: CapabilityAvailability = "available"

    def summary(self) -> dict[str, object]:
        return asdict(self)


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        key="project_state",
        name="Project State",
        purpose="Expose API health, the capability catalog and the runtime configuration.",
        contents=("API health", "capability catalog", "venues", "Agent identity", "disclaimers"),
        actions=("inspect health", "inspect configuration"),
        surfaces=("api", "mcp"),
    ),
    Capability(
        key="profiles",
        name="Users And Linked Accounts",
        purpose="Hunch users and the venue accounts (Alpaca, IBKR) linked to them.",
        contents=("HunchUserProfile", "HunchUserProfileAccount"),
        actions=(
            "read my profile",
            "update handle and display name",
            "link a venue account",
            "revoke a link",
            "read linked account holdings",
        ),
        surfaces=("api", "mcp"),
    ),
    Capability(
        key="takes",
        name="Takes",
        purpose="A person's thesis and its lifecycle, visibility and fork lineage.",
        contents=("HunchTake", "HunchTakeRevision"),
        actions=(
            "create",
            "edit",
            "set execution mode",
            "publish",
            "unpublish",
            "fork",
            "archive",
            "list own and published takes",
        ),
        surfaces=("api", "mcp"),
    ),
    Capability(
        key="instruments",
        name="Instruments",
        purpose="The FIGI-keyed US-listed universe Hunch can hold, with theme tags.",
        contents=("HunchInstrument", "ms-markets Asset, OpenFIGI details, snapshots, category"),
        actions=("list", "search", "read", "seed"),
        surfaces=("api", "mcp"),
    ),
    Capability(
        key="portfolios",
        name="Hunch Portfolios",
        purpose=(
            "Research a take, apply its constraints, publish the basket as an ms-markets signal "
            "and value it with the ms-markets portfolio graph."
        ),
        contents=(
            "HunchPortfolio (ms-markets Portfolio extension)",
            "SignalWeightsTS",
            "PortfolioWeightsTS",
            "PortfoliosTS",
            "ExternalPricesTS daily bars",
        ),
        actions=("build", "activate practice", "refresh", "revisions", "weights", "performance"),
        surfaces=("api", "mcp", "job"),
    ),
    Capability(
        key="funding",
        name="Funding And Execution",
        purpose=(
            "Fund a take into a linked account, propose trades, approve them or let autopilot "
            "act within limits, and delegate the orders to the venue connector."
        ),
        contents=(
            "HunchFunding",
            "HunchRebalanceProposal",
            "ms-markets VirtualFund, VirtualFundHoldingsTS, TargetPositionsTS",
            "ms-markets OrderManager, OrdersTS, TradesTS",
        ),
        actions=(
            "fund",
            "withdraw",
            "list fundings",
            "list proposals",
            "approve",
            "reject",
            "sync",
        ),
        surfaces=("api", "mcp", "job"),
    ),
    Capability(
        key="reviews",
        name="Daily Reviews",
        purpose="Review every active take daily: drift, thesis check, proposal or autopilot.",
        contents=("HunchDailyReview",),
        actions=("review now", "list reviews"),
        surfaces=("api", "mcp", "job"),
    ),
    Capability(
        key="community",
        name="Leaderboard And Notifications",
        purpose="Rank published takes by return since activation; keep every person informed.",
        contents=("HunchLeaderboardSnapshot", "HunchNotification"),
        actions=("read leaderboard", "list notifications", "mark read"),
        surfaces=("api", "mcp", "job"),
    ),
)


def capability_summaries() -> list[dict[str, object]]:
    return [capability.summary() for capability in CAPABILITIES]


__all__ = ["CAPABILITIES", "Capability", "CapabilityAvailability", "capability_summaries"]
