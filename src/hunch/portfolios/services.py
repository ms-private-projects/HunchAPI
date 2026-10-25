"""Hunch-owned construction of a take's portfolio.

Hunch, not a connector, turns a basket into a portfolio. The base ms-markets ``Portfolio`` row and
its ``HunchPortfolio`` extension are written together, so a Hunch portfolio never exists without
its take and a take's portfolio is always a Hunch one. Weights, rebalances and values are written
later by the portfolio graph (phase 1) against the base ``Portfolio.unique_identifier``.
"""

from __future__ import annotations

import uuid
from typing import Any

from hunch.portfolios import HunchPortfolio
from hunch.settings import HUNCH_PORTFOLIO_IDENTIFIER_PREFIX
from hunch.takes import Take
from msm.api.portfolios import Portfolio


def hunch_portfolio_identifier(take_uid: uuid.UUID | str) -> str:
    """The base ``Portfolio.unique_identifier`` of a take's portfolio."""
    return f"{HUNCH_PORTFOLIO_IDENTIFIER_PREFIX}__{uuid.UUID(str(take_uid)).hex}"


def create_hunch_portfolio(
    *,
    take: Take,
    calendar_uid: uuid.UUID | str,
    basket_revision: int = 1,
    is_simulated: bool = True,
    signal_uid: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> HunchPortfolio:
    """Create (or refresh) the ms-markets ``Portfolio`` and its ``HunchPortfolio`` extension.

    ``calendar_uid`` is the persisted trading calendar the portfolio graph rebalances on (XNYS
    for US equities). ``signal_uid`` is the take's weight signal once built; until then the base
    row has no signal pointer.
    """
    portfolio = Portfolio.upsert(
        unique_identifier=hunch_portfolio_identifier(take.uid),
        calendar_uid=calendar_uid,
        signal_uid=signal_uid or take.signal_uid,
    )
    return HunchPortfolio.upsert(
        portfolio_uid=portfolio.uid,
        take_uid=take.uid,
        owner_user_uid=take.owner_user_uid,
        basket_revision=basket_revision,
        is_simulated=is_simulated,
        metadata_json=metadata,
    )


def hunch_portfolio_for_take(take_uid: uuid.UUID | str) -> HunchPortfolio | None:
    """Return the take's portfolio extension row, or None before the take is built."""
    rows = HunchPortfolio.filter(take_uid=uuid.UUID(str(take_uid)), limit=1)
    return rows[0] if rows else None


__all__ = ["create_hunch_portfolio", "hunch_portfolio_for_take", "hunch_portfolio_identifier"]
