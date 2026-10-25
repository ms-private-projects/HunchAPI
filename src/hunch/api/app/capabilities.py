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
        actions=(),
        surfaces=("python",),
        availability="partial",
    ),
    Capability(
        key="takes",
        name="Takes",
        purpose="A person's thesis and its lifecycle, visibility and fork lineage.",
        contents=("HunchTake",),
        actions=("list own takes", "read a take"),
        surfaces=("mcp", "python"),
        availability="partial",
    ),
    Capability(
        key="portfolios",
        name="Hunch Portfolios",
        purpose="Hunch-built portfolios extending ms-markets Portfolio rows one-to-one.",
        contents=("HunchPortfolio", "ms-markets Portfolio"),
        actions=(),
        surfaces=("python",),
        availability="partial",
    ),
)


def capability_summaries() -> list[dict[str, object]]:
    return [capability.summary() for capability in CAPABILITIES]


__all__ = ["CAPABILITIES", "Capability", "CapabilityAvailability", "capability_summaries"]
