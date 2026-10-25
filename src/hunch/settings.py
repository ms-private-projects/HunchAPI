"""Project-wide constants and environment-driven configuration. Nothing here reads credentials."""

from __future__ import annotations

import os

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
REVISION_KINDS: tuple[str, ...] = ("initial", "rebalance", "user_edit", "thesis_check")

# Portfolio identity convention for the ms-markets `Portfolio` row behind a `HunchPortfolio`.
HUNCH_PORTFOLIO_IDENTIFIER_PREFIX = "HUNCH_PORTFOLIO"

# The trading calendar every Hunch portfolio rebalances and values on (US equities).
TRADING_CALENDAR_SOURCE = "XNYS"
TRADING_CALENDAR_IDENTIFIER = "XNYS"
TRADING_CALENDAR_SESSION = "regular"
TRADING_CALENDAR_VALID_FROM = "2024-01-01"
TRADING_CALENDAR_VALID_TO = "2028-12-31"

# Cash is a `currency` Asset position, as the connectors model it.
CASH_ASSET_IDENTIFIER = "USD"

# The ms-markets AssetCategory that holds every instrument Hunch knows (price coverage).
UNIVERSE_CATEGORY_IDENTIFIER = "HUNCH_UNIVERSE"

# Research modes: `inference` records model calls through the platform; `heuristic` is the
# deterministic keyword matcher used for tests and when no model provider is configured.
RESEARCH_MODES: tuple[str, ...] = ("inference", "heuristic")
# Where a take build runs: `inline` in the API process (local development) or as a platform
# Job (`job`, hosted).
BUILD_EXECUTIONS: tuple[str, ...] = ("inline", "job")
# Daily bar providers: `synthetic` for local development and tests; `alpaca` is a later phase.
BARS_PROVIDERS: tuple[str, ...] = ("synthetic",)


def _choice(name: str, default: str, allowed: tuple[str, ...]) -> str:
    value = os.environ.get(name, default).strip().lower() or default
    if value not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(allowed)}.")
    return value


def research_mode() -> str:
    return _choice("HUNCH_RESEARCH_MODE", "inference", RESEARCH_MODES)


def build_execution() -> str:
    return _choice("HUNCH_BUILD_EXECUTION", "inline", BUILD_EXECUTIONS)


def bars_provider() -> str:
    return _choice("HUNCH_BARS_PROVIDER", "synthetic", BARS_PROVIDERS)


def inference_provider() -> str:
    return os.environ.get("HUNCH_INFERENCE_PROVIDER", "openai-codex").strip() or "openai-codex"


def inference_model() -> str:
    return os.environ.get("HUNCH_INFERENCE_MODEL", "gpt-5.6-luna").strip() or "gpt-5.6-luna"


def inference_environment_uid() -> str | None:
    """The Organization Environment recorded inference runs in, when the checkout resolves none.

    A hosted runtime derives it; a local checkout whose branch is not registered sets
    `HUNCH_INFERENCE_ENVIRONMENT_UID` to the Environment that holds the model credential.
    """
    value = os.environ.get("HUNCH_INFERENCE_ENVIRONMENT_UID", "").strip()
    return value or None


def inference_thinking() -> str | None:
    value = os.environ.get("HUNCH_INFERENCE_THINKING", "medium").strip().lower()
    return value or None


__all__ = [
    "ACCOUNT_LINK_STATUSES",
    "BARS_PROVIDERS",
    "BUILD_EXECUTIONS",
    "CASH_ASSET_IDENTIFIER",
    "EXECUTION_MODES",
    "HUNCH_PORTFOLIO_IDENTIFIER_PREFIX",
    "MIGRATION_NAMESPACE",
    "PROJECT_NAMESPACE_SLUG",
    "RESEARCH_MODES",
    "REVISION_KINDS",
    "TAKE_STATUSES",
    "TAKE_VISIBILITIES",
    "TRADING_CALENDAR_IDENTIFIER",
    "TRADING_CALENDAR_SESSION",
    "TRADING_CALENDAR_SOURCE",
    "TRADING_CALENDAR_VALID_FROM",
    "TRADING_CALENDAR_VALID_TO",
    "UNIVERSE_CATEGORY_IDENTIFIER",
    "VENUES",
    "VENUE_ALPACA",
    "VENUE_IBKR",
    "bars_provider",
    "build_execution",
    "inference_environment_uid",
    "inference_model",
    "inference_provider",
    "inference_thinking",
    "research_mode",
]
