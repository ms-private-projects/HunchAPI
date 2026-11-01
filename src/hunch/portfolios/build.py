"""Building a take: research → guardrails → revision → signal → portfolio graph.

Hunch owns this pipeline end to end. It is deterministic service code; the model is called as a
recorded function inside research, and a build never talks to a brokerage.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from hunch.instruments import HunchInstrument
from hunch.instruments.services import cached_instruments, ensure_universe, instruments_by_figi
from hunch.market_data import ensure_daily_bars, last_completed_session_close, latest_closes
from hunch.portfolios import HunchPortfolio
from hunch.portfolios.graph import (
    PortfolioGraph,
    ensure_trading_calendar,
    portfolio_latest_weights,
    portfolio_value_points,
)
from hunch.portfolios.services import hunch_portfolio_identifier
from hunch.portfolios.signal import basket_signal, publish_basket_observation
from hunch.profiles import utc_now
from hunch.research import BasketProposal, propose_basket
from hunch.takes import Take
from hunch.takes.revisions import TakeRevision
from hunch.takes.services import TakeStateError
from msm.api.portfolios import Portfolio

UTC = dt.timezone.utc


@dataclass(slots=True)
class BuildResult:
    take: Take
    revision: TakeRevision
    hunch_portfolio: HunchPortfolio
    portfolio_identifier: str
    signal_uid: str
    proposal: BasketProposal
    value_points: list[dict[str, Any]] = field(default_factory=list)


def take_revisions(take_uid: uuid.UUID | str) -> list[TakeRevision]:
    rows = TakeRevision.filter(take_uid=uuid.UUID(str(take_uid)), limit=500)
    return sorted(rows, key=lambda row: row.revision)


def take_universe(take_uid: uuid.UUID | str, *extra: str) -> list[str]:
    """Every instrument the take ever held, plus the ones being added."""
    figis: list[str] = []
    for revision in take_revisions(take_uid):
        figis.extend(item["figi"] for item in revision.weights_json)
    figis.extend(extra)
    return sorted(dict.fromkeys(figis))


def build_take(
    take_uid: uuid.UUID | str,
    *,
    research_mode: str | None = None,
    now: dt.datetime | None = None,
    created_by: str | None = None,
) -> BuildResult:
    """Research the take, publish its basket, and (re)build its portfolio."""
    take = Take.get_by_uid(uuid.UUID(str(take_uid)))
    if take is None:
        raise LookupError(f"Take {take_uid} does not exist.")
    if take.status == "archived":
        raise TakeStateError("An archived take cannot be built.")
    moment = (now or dt.datetime.now(UTC)).astimezone(UTC)

    instruments: list[HunchInstrument] = ensure_universe()
    # Research reads the stored bars (the quant evidence source). On the first build in an
    # Environment no bars exist yet and the read fails before the table has a registered update,
    # so write the universe's bars first.
    universe_figis = [row.figi for row in instruments]
    ensure_daily_bars(universe_figis, end=moment.date())
    previous = take_revisions(take.uid)
    revision_number = (previous[-1].revision + 1) if previous else 1
    proposal = propose_basket(take, instruments, mode=research_mode, revision=revision_number)
    weights = proposal.weights_by_figi()

    universe = take_universe(take.uid, *weights)
    # Only a name the take held that has since left the universe still lacks fresh bars.
    departed = sorted(set(universe) - set(universe_figis))
    if departed:
        ensure_daily_bars(departed, end=moment.date())
    calendar = ensure_trading_calendar()

    signal_time = last_completed_session_close(moment)
    signal = basket_signal(take.uid, universe)
    publish_basket_observation(
        signal, weights, signal_time, description=f"Hunch take {take.uid}: {take.title}"
    )

    portfolio_row = Portfolio.upsert(
        unique_identifier=hunch_portfolio_identifier(take.uid),
        calendar_uid=calendar.uid,
        signal_uid=signal.signal_uid,
    )
    hunch_portfolio = HunchPortfolio.upsert(
        portfolio_uid=portfolio_row.uid,
        take_uid=take.uid,
        owner_user_uid=take.owner_user_uid,
        basket_revision=revision_number,
        is_simulated=True,
        activated_at=take.activated_at,
        metadata_json={
            "research_mode": proposal.research.mode,
            "price_source": "ExternalPricesTS",
            "rebalance": "XNYS market_close, every session",
        },
    )
    graph = PortfolioGraph(
        portfolio=portfolio_row,
        signal=signal,
        description=proposal.rationale_md[:500] or None,
        offset_start=signal_time - dt.timedelta(days=1),
    )
    graph.run()

    revision = TakeRevision.create(
        take_uid=take.uid,
        revision=revision_number,
        kind="initial" if revision_number == 1 else "rebalance",
        rationale_md=proposal.rationale_md,
        weights_json=[item.model_dump() for item in proposal.weights],
        research_json={
            "brief": proposal.research.brief.model_dump(),
            "candidates": [c.model_dump() for c in proposal.research.candidates],
            "guardrail_notes": proposal.guardrail_notes,
            "cash_weight": proposal.cash_weight,
            "conversation_uid": proposal.research.conversation_uid,
            "evidence": [item.model_dump(mode="json") for item in proposal.research.evidence],
        },
        inference_request_uids=proposal.research.inference_request_uids or None,
        created_by=created_by or proposal.research.mode,
        signal_time_index=signal_time,
        created_at=utc_now(),
    )
    new_status = "built" if take.status in ("draft", "built") else take.status
    updated = Take.update(
        take.uid, status=new_status, signal_uid=signal.signal_uid, updated_at=utc_now()
    )
    return BuildResult(
        take=updated,
        revision=revision,
        hunch_portfolio=hunch_portfolio,
        portfolio_identifier=portfolio_row.unique_identifier,
        signal_uid=signal.signal_uid,
        proposal=proposal,
        value_points=portfolio_value_points(portfolio_row.unique_identifier),
    )


def activate_practice(take_uid: uuid.UUID | str, *, now: dt.datetime | None = None) -> Take:
    """Start the take's performance record as a practice (simulated) portfolio."""
    take = Take.get_by_uid(uuid.UUID(str(take_uid)))
    if take is None:
        raise LookupError(f"Take {take_uid} does not exist.")
    if take.status == "active_practice":
        return take
    if take.status != "built":
        raise TakeStateError("Build the take before activating it.")
    moment = utc_now() if now is None else now
    portfolios = HunchPortfolio.filter(take_uid=take.uid, limit=1)
    if portfolios:
        HunchPortfolio.update(portfolios[0].uid, activated_at=moment, is_simulated=True)
    return Take.update(take.uid, status="active_practice", activated_at=moment, updated_at=moment)


def refresh_take_portfolio(
    take_uid: uuid.UUID | str, *, now: dt.datetime | None = None
) -> dict[str, Any]:
    """Bring prices up to date and extend the take's portfolio values."""
    take = Take.get_by_uid(uuid.UUID(str(take_uid)))
    if take is None:
        raise LookupError(f"Take {take_uid} does not exist.")
    revisions = take_revisions(take.uid)
    if not revisions:
        raise TakeStateError("The take has not been built.")
    moment = (now or dt.datetime.now(UTC)).astimezone(UTC)
    universe = take_universe(take.uid)
    ensure_daily_bars(universe, end=moment.date())
    portfolio_row = Portfolio.get_by_unique_identifier(hunch_portfolio_identifier(take.uid))
    if portfolio_row is None:
        raise TakeStateError("The take's portfolio does not exist.")
    first_signal = revisions[0].signal_time_index or moment
    graph = PortfolioGraph(
        portfolio=portfolio_row,
        signal=basket_signal(take.uid, universe),
        offset_start=first_signal - dt.timedelta(days=1),
    )
    return graph.run()


def take_performance(take: Take) -> list[dict[str, Any]]:
    """NAV points since activation, rebased to 1.0 at the last value at or before activation.

    Before activation (or without one) every value is returned, rebased to the first.
    """
    points = portfolio_value_points(hunch_portfolio_identifier(take.uid))
    if not points:
        return []
    start_index = 0
    if take.activated_at is not None:
        activated = pd.Timestamp(take.activated_at)
        for index, row in enumerate(points):
            if pd.Timestamp(row["time_index"]) <= activated:
                start_index = index
    window = points[start_index:]
    base = float(window[0]["close"]) or 1.0
    return [
        {
            "time_index": row["time_index"],
            "close": float(row["close"]) / base,
            "return": float(row["return"]) if row.get("return") is not None else None,
        }
        for row in window
    ]


def take_weights(take: Take) -> list[dict[str, Any]]:
    """Latest portfolio weights with instrument identity, heaviest first.

    The Basket tab loads this on every visit, so it reads as little as it can: the weights
    snapshot, the instrument rows from the process cache, and the last closes only for rows the
    graph stored without an execution price.
    """
    rows = portfolio_latest_weights(hunch_portfolio_identifier(take.uid))
    instruments = instruments_by_figi(cached_instruments())
    unpriced = [str(row["asset_identifier"]) for row in rows if row.get("price_current") is None]
    closes = latest_closes(unpriced) if unpriced else {}
    out = []
    for row in rows:
        instrument = instruments.get(str(row["asset_identifier"]))
        close = closes.get(str(row["asset_identifier"]))
        out.append(
            {
                "figi": row["asset_identifier"],
                "ticker": instrument.ticker if instrument else None,
                "name": instrument.name if instrument else None,
                "weight": float(row["weight"]),
                "price": row.get("price_current") or (close[1] if close else None),
                "time_index": row["time_index"],
            }
        )
    out.sort(key=lambda item: -item["weight"])
    return [item for item in out if item["weight"] > 0]


__all__ = [
    "BuildResult",
    "activate_practice",
    "build_take",
    "refresh_take_portfolio",
    "take_performance",
    "take_revisions",
    "take_universe",
    "take_weights",
]
