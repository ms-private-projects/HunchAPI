"""Project-wide constants and environment-driven configuration. Nothing here reads credentials."""

from __future__ import annotations

import os
from dataclasses import dataclass

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

# Funding and execution lifecycle (ADR 0003).
FUNDING_STATUSES: tuple[str, ...] = (
    "planned",
    "pending_initial",
    "active",
    "withdrawing",
    "closed",
    "failed",
)
PROPOSAL_TRIGGERS: tuple[str, ...] = ("initial", "drift", "thesis", "user", "withdrawal")
PROPOSAL_STATUSES: tuple[str, ...] = (
    "proposed",
    "approved",
    "rejected",
    "expired",
    "submitted",
    "partially_filled",
    "filled",
    "failed",
)
PROPOSAL_OPEN_STATUSES: tuple[str, ...] = ("proposed", "approved", "submitted", "partially_filled")
REVIEW_OUTCOMES: tuple[str, ...] = ("hold", "flagged", "proposed", "executed")
NOTIFICATION_KINDS: tuple[str, ...] = (
    "take_built",
    "review_hold",
    "review_proposed",
    "proposal_awaiting_approval",
    "proposal_executed",
    "proposal_failed",
    "funding_active",
    "funding_closed",
    "account_linked",
    "take_forked",
)

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
# How the scheduled review sweep runs: `inline` reviews every active take in the sweep's own
# process (local development); `job` starts one `Hunch Daily Review` Job run per take, in small
# batches, so the reviews run on that Job's model credential and in parallel (hosted dispatcher).
REVIEW_DISPATCHES: tuple[str, ...] = ("inline", "job")
# Daily bar providers (ADR 0009): `synthetic` (the default) for tests and offline development;
# `alpaca` reads the daily bars the Alpaca connector stores, through its REST API.
BARS_PROVIDERS: tuple[str, ...] = ("synthetic", "alpaca")
# Venue connectors: `live` calls the Alpaca and IBKR connector applications over HTTP;
# `simulated` keeps a local venue inside this process that writes the same ms-markets rows.
CONNECTOR_MODES: tuple[str, ...] = ("live", "simulated")
SIMULATED_ACCOUNT_IDENTIFIER_PREFIX = "SIM"
SIMULATED_STARTING_CASH = 100_000.0


def _choice(name: str, default: str, allowed: tuple[str, ...]) -> str:
    value = os.environ.get(name, default).strip().lower() or default
    if value not in allowed:
        raise ValueError(f"{name} must be one of: {', '.join(allowed)}.")
    return value


def research_mode() -> str:
    return _choice("HUNCH_RESEARCH_MODE", "inference", RESEARCH_MODES)


def build_execution() -> str:
    return _choice("HUNCH_BUILD_EXECUTION", "inline", BUILD_EXECUTIONS)


def review_dispatch() -> str:
    return _choice("HUNCH_REVIEW_DISPATCH", "inline", REVIEW_DISPATCHES)


def bars_provider() -> str:
    return _choice("HUNCH_BARS_PROVIDER", "synthetic", BARS_PROVIDERS)


def connector_mode() -> str:
    return _choice("HUNCH_CONNECTOR_MODE", "live", CONNECTOR_MODES)


def connector_url(venue: str) -> str | None:
    """The base URL of a venue connector release (HUNCH_ALPACA_CONNECTOR_URL, ...)."""
    value = os.environ.get(f"HUNCH_{venue.upper()}_CONNECTOR_URL", "").strip()
    return value.rstrip("/") or None


def connector_release_uid(venue: str) -> str | None:
    value = os.environ.get(f"HUNCH_{venue.upper()}_CONNECTOR_RELEASE_UID", "").strip()
    return value or None


def inference_provider() -> str:
    return os.environ.get("HUNCH_INFERENCE_PROVIDER", "meta").strip() or "meta"


def inference_model() -> str:
    return os.environ.get("HUNCH_INFERENCE_MODEL", "muse-spark-1.3").strip() or "muse-spark-1.3"


def inference_credential() -> str | None:
    """The configured credential (its `custom_id`) recorded inference selects; None for the default.

    The platform then uses the workload's first owned credential, then the first shared one.
    """
    value = os.environ.get("HUNCH_INFERENCE_CREDENTIAL", "").strip()
    return value or None


# Model roles: each kind of recorded model call Hunch makes selects its own provider, model,
# thinking level and credential, so one deployment can mix models. The Hunch Agent's own
# conversation model is the Harness Agent declaration in the workflow file, not a role here.
# Every role starts from the shared `HUNCH_INFERENCE_*` selection; `HUNCH_MODEL_<ROLE>` overrides
# it with space-separated `key=value` pairs, for example
# `HUNCH_MODEL_RESEARCH="model=muse-wonder-1.0 thinking=medium"`.
# Model identifiers may contain `/` and `:`; a key missing from the override keeps the shared value.
MODEL_ROLE_RESEARCH = "research"  # a take build: thesis to candidates
MODEL_ROLE_REVIEW = "review"  # the daily thesis check of an active take
MODEL_ROLE_ANALYSIS = "analysis"  # analysis-only tools that answer a person synchronously
MODEL_ROLES: tuple[str, ...] = (MODEL_ROLE_RESEARCH, MODEL_ROLE_REVIEW, MODEL_ROLE_ANALYSIS)
MODEL_ROLE_KEYS: tuple[str, ...] = ("provider", "model", "thinking", "credential")
THINKING_LEVELS: tuple[str, ...] = ("off", "minimal", "low", "medium", "high", "xhigh", "max")


@dataclass(frozen=True, slots=True)
class ModelSelection:
    """The provider, model, thinking level and credential one model role runs on."""

    role: str
    provider: str
    model: str
    thinking: str | None = None
    credential: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "provider": self.provider,
            "model": self.model,
            "thinking": self.thinking,
            "credential": self.credential,
        }


def model_role(role: str) -> ModelSelection:
    """The model selection of one role: the shared defaults, then `HUNCH_MODEL_<ROLE>` overrides."""
    if role not in MODEL_ROLES:
        raise ValueError(f"Unknown model role {role!r}; roles are: {', '.join(MODEL_ROLES)}.")
    selected: dict[str, str | None] = {
        "provider": inference_provider(),
        "model": inference_model(),
        "thinking": inference_thinking(),
        "credential": inference_credential(),
    }
    name = f"HUNCH_MODEL_{role.upper()}"
    for pair in os.environ.get(name, "").split():
        key, separator, value = pair.partition("=")
        if not separator or key not in MODEL_ROLE_KEYS or not value:
            raise ValueError(
                f"{name} holds space-separated key=value pairs with keys: "
                f"{', '.join(MODEL_ROLE_KEYS)}."
            )
        selected[key] = value
    thinking = selected["thinking"]
    if thinking is not None and thinking not in THINKING_LEVELS:
        raise ValueError(
            f"{name}: thinking must be one of {', '.join(THINKING_LEVELS)}, not {thinking!r}."
        )
    return ModelSelection(
        role=role,
        provider=str(selected["provider"]),
        model=str(selected["model"]),
        thinking=thinking,
        credential=selected["credential"],
    )


def model_roles() -> dict[str, ModelSelection]:
    """Every role's selection, for the configuration the site and the Agent read."""
    return {role: model_role(role) for role in MODEL_ROLES}


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
    "CONNECTOR_MODES",
    "EXECUTION_MODES",
    "FUNDING_STATUSES",
    "HUNCH_PORTFOLIO_IDENTIFIER_PREFIX",
    "NOTIFICATION_KINDS",
    "PROPOSAL_OPEN_STATUSES",
    "PROPOSAL_STATUSES",
    "PROPOSAL_TRIGGERS",
    "REVIEW_OUTCOMES",
    "MIGRATION_NAMESPACE",
    "MODEL_ROLES",
    "MODEL_ROLE_ANALYSIS",
    "MODEL_ROLE_KEYS",
    "MODEL_ROLE_RESEARCH",
    "MODEL_ROLE_REVIEW",
    "PROJECT_NAMESPACE_SLUG",
    "RESEARCH_MODES",
    "REVIEW_DISPATCHES",
    "REVISION_KINDS",
    "THINKING_LEVELS",
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
    "connector_mode",
    "connector_release_uid",
    "connector_url",
    "ModelSelection",
    "inference_credential",
    "inference_environment_uid",
    "inference_model",
    "inference_provider",
    "inference_thinking",
    "model_role",
    "model_roles",
    "research_mode",
    "review_dispatch",
]
