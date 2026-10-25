"""Project-wide constants. Nothing here reads credentials."""

from __future__ import annotations

# Project namespace slug: the ms-markets physical-table app segment of every Hunch MetaTable
# (`hunch__<table>`), the MetaTables migration namespace and the migration catalog key.
PROJECT_NAMESPACE_SLUG = "hunch"
MIGRATION_NAMESPACE = "hunch"

# The brokerage venues whose connectors Hunch talks to. Each is a separate Main Sequence
# application; Hunch never holds a broker credential.
VENUE_ALPACA = "alpaca"
VENUE_IBKR = "ibkr"
VENUES: tuple[str, ...] = (VENUE_ALPACA, VENUE_IBKR)

# Account link lifecycle: `pending` while the person enters keys on the connector's site,
# `active` once the connector-created Account is verified as theirs, `revoked` when unlinked.
ACCOUNT_LINK_STATUSES: tuple[str, ...] = ("pending", "active", "revoked")

# Take lifecycle (see docs/planning/0001, section 3.6).
TAKE_STATUSES: tuple[str, ...] = (
    "draft",
    "built",
    "active_practice",
    "funding",
    "active_funded",
    "archived",
)
TAKE_VISIBILITIES: tuple[str, ...] = ("private", "public")
EXECUTION_MODES: tuple[str, ...] = ("practice", "approval", "autopilot")

# Portfolio identity convention for the ms-markets `Portfolio` row behind a `HunchPortfolio`.
HUNCH_PORTFOLIO_IDENTIFIER_PREFIX = "HUNCH_PORTFOLIO"

__all__ = [
    "ACCOUNT_LINK_STATUSES",
    "EXECUTION_MODES",
    "HUNCH_PORTFOLIO_IDENTIFIER_PREFIX",
    "MIGRATION_NAMESPACE",
    "PROJECT_NAMESPACE_SLUG",
    "TAKE_STATUSES",
    "TAKE_VISIBILITIES",
    "VENUES",
    "VENUE_ALPACA",
    "VENUE_IBKR",
]
