"""Funded takes: funding, proposals, approvals, autopilot, execution sync and withdrawal.

Hunch decides *what* to trade here (targets, legs, limits, state); the venue connector decides
*how* (orders, fills). Every write to the brokerage side goes through ``hunch.connectors``; the
money-side records are ms-markets rows written by ``hunch.funding.ledger``.
"""

from __future__ import annotations

import datetime as dt
import math
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from hunch.community.notifications import notify
from hunch.connectors import (
    ConnectorCapabilityUnavailable,
    ConnectorError,
    OrderLeg,
    OrderState,
    VenueAssetRef,
    VenueConnector,
    connector_for,
)
from hunch.funding import HunchFunding, HunchRebalanceProposal
from hunch.funding.ledger import (
    ensure_virtual_fund,
    fund_identifier,
    fund_latest_holdings,
    publish_account_target,
    write_fund_holdings,
)
from hunch.instruments.services import ensure_universe, instruments_by_figi
from hunch.market_data import latest_closes, session_schedule
from hunch.portfolios.services import hunch_portfolio_for_take
from hunch.profiles import HunchUserProfileAccount, utc_now
from hunch.settings import CASH_ASSET_IDENTIFIER, PROPOSAL_OPEN_STATUSES
from hunch.takes import Take
from hunch.takes.services import TakeStateError, owned_take

UTC = dt.timezone.utc
MIN_LEG_NOTIONAL = 1.0
FUNDABLE_TAKE_STATUSES: tuple[str, ...] = ("built", "active_practice")
CLOSED_FUNDING_STATUSES: tuple[str, ...] = ("closed", "failed")


class FundingError(ValueError):
    """A funding or execution rule refused the request (HTTP 409)."""


class AutopilotPolicy(BaseModel):
    """Server-enforced limits an autopilot take must satisfy to trade without approval."""

    model_config = ConfigDict(extra="forbid")

    max_turnover_per_day: float = Field(default=0.25, gt=0, le=1.0)
    max_notional_per_order: float = Field(default=25_000.0, gt=0)
    max_single_name_weight: float = Field(default=0.20, gt=0, le=1.0)
    allow_new_instruments: bool = True
    trading_window: Literal["session", "any"] = "any"


class FundingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_account_uid: uuid.UUID
    target_notional: float = Field(ge=100.0, le=50_000_000.0)
    execution_mode: Literal["approval", "autopilot"] = "approval"
    autopilot_policy: AutopilotPolicy | None = None


# -- lookups ------------------------------------------------------------------------------------


def active_link(user_uid: str, profile_account_uid: uuid.UUID | str) -> HunchUserProfileAccount:
    link = HunchUserProfileAccount.get_by_uid(uuid.UUID(str(profile_account_uid)))
    if link is None or link.user_uid != user_uid:
        raise LookupError("The linked account does not exist.")
    if link.status != "active":
        raise FundingError(f"The linked account is {link.status}; only active links can be funded.")
    return link


def funding_for_take(take_uid: uuid.UUID | str) -> HunchFunding | None:
    rows = HunchFunding.filter(take_uid=uuid.UUID(str(take_uid)))
    return rows[0] if rows else None


def active_funding_for_take(take_uid: uuid.UUID | str) -> HunchFunding | None:
    funding = funding_for_take(take_uid)
    if funding is None or funding.status in CLOSED_FUNDING_STATUSES:
        return None
    return funding


def owned_funding(user_uid: str, funding_uid: uuid.UUID | str) -> HunchFunding:
    funding = HunchFunding.get_by_uid(uuid.UUID(str(funding_uid)))
    if funding is None or funding.owner_user_uid != user_uid:
        raise LookupError("The funding does not exist.")
    return funding


def list_fundings(user_uid: str) -> list[HunchFunding]:
    rows = HunchFunding.filter(owner_user_uid=user_uid, limit=5000)
    return sorted(
        rows, key=lambda row: row.created_at or dt.datetime.min.replace(tzinfo=UTC), reverse=True
    )


def owned_proposal(user_uid: str, proposal_uid: uuid.UUID | str) -> HunchRebalanceProposal:
    proposal = HunchRebalanceProposal.get_by_uid(uuid.UUID(str(proposal_uid)))
    if proposal is None or proposal.owner_user_uid != user_uid:
        raise LookupError("The proposal does not exist.")
    return proposal


def list_proposals(
    user_uid: str,
    *,
    status: str | None = None,
    take_uid: uuid.UUID | str | None = None,
    open_only: bool = False,
) -> list[HunchRebalanceProposal]:
    filters: dict[str, Any] = {"owner_user_uid": user_uid, "limit": 5000}
    if status:
        filters["status"] = status
    if take_uid is not None:
        filters["take_uid"] = uuid.UUID(str(take_uid))
    rows = HunchRebalanceProposal.filter(**filters)
    if open_only:
        rows = [row for row in rows if row.status in PROPOSAL_OPEN_STATUSES]
    return sorted(
        rows, key=lambda row: row.created_at or dt.datetime.min.replace(tzinfo=UTC), reverse=True
    )


def open_proposals_for_take(take_uid: uuid.UUID | str) -> list[HunchRebalanceProposal]:
    rows = HunchRebalanceProposal.filter(take_uid=uuid.UUID(str(take_uid)), limit=5000)
    return [row for row in rows if row.status in PROPOSAL_OPEN_STATUSES]


# -- pricing and fund state ---------------------------------------------------------------------


def _prices(figis: list[str]) -> dict[str, float]:
    return (
        {figi: float(close) for figi, (_, close) in latest_closes(figis).items()} if figis else {}
    )


def _fund_state(funding: HunchFunding) -> tuple[dt.datetime | None, dict[str, float]]:
    if funding.virtual_fund_uid is None:
        return None, {}
    return fund_latest_holdings(funding.virtual_fund_uid)


def _positions(state: dict[str, float]) -> dict[str, float]:
    return {
        asset: qty
        for asset, qty in state.items()
        if asset != CASH_ASSET_IDENTIFIER and abs(qty) > 1e-9
    }


def _nav(state: dict[str, float], prices: dict[str, float]) -> float:
    value = float(state.get(CASH_ASSET_IDENTIFIER, 0.0))
    for asset, qty in _positions(state).items():
        value += qty * prices.get(asset, 0.0)
    return value


def fund_weights(funding: HunchFunding) -> dict[str, float] | None:
    """The fund's current weights by FIGI (cash excluded), valued at the last stored closes."""
    _, state = _fund_state(funding)
    positions = _positions(state)
    if not positions and not state:
        return None
    prices = _prices(list(positions))
    nav = _nav(state, prices)
    if nav <= 0:
        return None
    return {asset: round(qty * prices.get(asset, 0.0) / nav, 6) for asset, qty in positions.items()}


def account_weights_for_take(take_uid: uuid.UUID | str) -> dict[str, float] | None:
    funding = active_funding_for_take(take_uid)
    if funding is None or funding.status != "active":
        return None
    return fund_weights(funding) or {}


def fund_summary(funding: HunchFunding) -> dict[str, Any]:
    time_index, state = _fund_state(funding)
    positions = _positions(state)
    prices = _prices(list(positions))
    nav = _nav(state, prices)
    instruments = instruments_by_figi(ensure_universe()) if positions else {}
    return {
        "as_of": time_index,
        "nav": round(nav, 2),
        "cash": round(float(state.get(CASH_ASSET_IDENTIFIER, 0.0)), 2),
        "invested": round(nav - float(state.get(CASH_ASSET_IDENTIFIER, 0.0)), 2),
        "return_on_notional": round(nav / funding.target_notional - 1.0, 6)
        if funding.target_notional
        else None,
        "positions": [
            {
                "figi": asset,
                "ticker": instruments[asset].ticker if asset in instruments else None,
                "quantity": round(qty, 4),
                "price": prices.get(asset),
                "value": round(qty * prices.get(asset, 0.0), 2),
                "weight": round(qty * prices.get(asset, 0.0) / nav, 6) if nav > 0 else None,
            }
            for asset, qty in sorted(
                positions.items(), key=lambda item: -item[1] * prices.get(item[0], 0.0)
            )
        ],
    }


# -- legs ---------------------------------------------------------------------------------------


def _target_weights(take: Take) -> dict[str, float]:
    from hunch.reviews.services import target_weights

    return target_weights(take)


def next_session_close(now: dt.datetime) -> dt.datetime:
    schedule = session_schedule(now.date(), now.date() + dt.timedelta(days=10))
    cutoff = now + dt.timedelta(hours=20)
    for close in schedule["market_close"]:
        if close.to_pydatetime() > cutoff:
            return close.to_pydatetime()
    return now + dt.timedelta(days=2)


def compute_legs(
    *,
    proposal_uid: uuid.UUID,
    target: dict[str, float],
    notional: float,
    current: dict[str, float],
    prices: dict[str, float],
    venue_assets: dict[str, VenueAssetRef],
    cash_available: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Trades that move ``current`` (signed quantities by FIGI) to ``target`` × ``notional``."""
    instruments = instruments_by_figi(ensure_universe())
    notes: list[str] = []
    legs: list[dict[str, Any]] = []
    nav = max(notional, 1e-9)
    for figi in sorted(set(target) | set(current)):
        price = prices.get(figi)
        if price is None or price <= 0:
            notes.append(f"{figi}: no stored price, skipped")
            continue
        ref = venue_assets.get(figi)
        if ref is None:
            notes.append(f"{figi}: not tradable at the venue, skipped")
            continue
        weight = float(target.get(figi, 0.0))
        wanted = weight * notional / price
        wanted = round(wanted, 4) if ref.fractionable else float(math.floor(wanted + 1e-9))
        held = float(current.get(figi, 0.0))
        delta = round(wanted - held, 4)
        if abs(delta) * price < MIN_LEG_NOTIONAL or abs(delta) < 1e-6:
            continue
        instrument = instruments.get(figi)
        legs.append(
            {
                "client_order_id": f"{proposal_uid.hex}:{len(legs) + 1:02d}",
                "figi": figi,
                "ticker": ref.symbol or (instrument.ticker if instrument else figi),
                "name": instrument.name if instrument else None,
                "asset_identifier": ref.asset_identifier,
                "side": "buy" if delta > 0 else "sell",
                "quantity": abs(delta),
                "estimated_price": round(price, 4),
                "estimated_notional": round(abs(delta) * price, 2),
                "target_weight": round(weight, 6),
                "current_weight": round(held * price / nav, 6),
                "reason": "new position"
                if held == 0 and delta > 0
                else ("exit" if weight == 0 else "rebalance"),
            }
        )
    sells = [leg for leg in legs if leg["side"] == "sell"]
    buys = [leg for leg in legs if leg["side"] == "buy"]
    proceeds = sum(leg["estimated_notional"] for leg in sells)
    cost = sum(leg["estimated_notional"] for leg in buys)
    budget = cash_available + proceeds
    if cost > budget + 0.01 and cost > 0:
        scale = max(budget, 0.0) / cost
        notes.append(f"buys scaled to {scale:.1%} of target to fit available cash")
        for leg in buys:
            ref = venue_assets[leg["figi"]]
            quantity = leg["quantity"] * scale
            quantity = (
                round(quantity, 4) if ref.fractionable else float(math.floor(quantity + 1e-9))
            )
            leg["quantity"] = quantity
            leg["estimated_notional"] = round(quantity * leg["estimated_price"], 2)
        buys = [
            leg
            for leg in buys
            if leg["quantity"] > 0 and leg["estimated_notional"] >= MIN_LEG_NOTIONAL
        ]
    return sells + buys, notes


def autopilot_check(
    policy: AutopilotPolicy,
    legs: list[dict[str, Any]],
    *,
    nav: float,
    current: dict[str, float],
    target: dict[str, float],
    now: dt.datetime,
) -> dict[str, Any]:
    reasons: list[str] = []
    turnover = sum(leg["estimated_notional"] for leg in legs) / nav if nav > 0 else 1.0
    if turnover > policy.max_turnover_per_day:
        reasons.append(f"turnover {turnover:.1%} exceeds {policy.max_turnover_per_day:.1%}")
    biggest = max((leg["estimated_notional"] for leg in legs), default=0.0)
    if biggest > policy.max_notional_per_order:
        reasons.append(f"an order of {biggest:,.0f} exceeds {policy.max_notional_per_order:,.0f}")
    heaviest = max(target.values(), default=0.0)
    if heaviest > policy.max_single_name_weight + 1e-9:
        reasons.append(
            f"a target weight of {heaviest:.1%} exceeds {policy.max_single_name_weight:.1%}"
        )
    if not policy.allow_new_instruments:
        new = [leg["ticker"] for leg in legs if leg["side"] == "buy" and leg["figi"] not in current]
        if new:
            reasons.append("new instruments are not allowed: " + ", ".join(new))
    if policy.trading_window == "session":
        schedule = session_schedule(now.date(), now.date())
        in_session = any(
            row.market_open.to_pydatetime() <= now <= row.market_close.to_pydatetime()
            for row in schedule.itertuples()
        )
        if not in_session:
            reasons.append("outside the trading session")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "turnover": round(turnover, 6),
        "largest_order_notional": round(biggest, 2),
        "policy": policy.model_dump(),
        "checked_at": now.isoformat(),
    }


# -- funding ------------------------------------------------------------------------------------


def _link_and_connector(funding: HunchFunding) -> tuple[HunchUserProfileAccount, VenueConnector]:
    link = HunchUserProfileAccount.get_by_uid(funding.profile_account_uid)
    if link is None:
        raise FundingError("The linked account no longer exists.")
    return link, connector_for(link.venue)


def fund_take(
    user_uid: str, take_uid: uuid.UUID | str, request: FundingRequest
) -> tuple[HunchFunding, HunchRebalanceProposal]:
    """Fund a built take into one linked account and propose (or autopilot) the initial trades."""
    take = owned_take(user_uid, take_uid)
    if active_funding_for_take(take.uid) is not None:
        raise FundingError("The take is already funded; withdraw it before funding again.")
    if take.status not in FUNDABLE_TAKE_STATUSES:
        raise TakeStateError(f"A take in status {take.status} cannot be funded; build it first.")
    link = active_link(user_uid, request.profile_account_uid)
    connector = connector_for(link.venue)
    account = connector.get_account(str(link.account_uid))
    if account is None or not account.is_active:
        raise FundingError("The venue account is not available at the connector.")
    snapshot = connector.latest_holdings(str(link.account_uid)) or connector.capture_holdings(
        str(link.account_uid)
    )
    cash = snapshot.cash(account.currency or CASH_ASSET_IDENTIFIER)
    if cash + 0.01 < request.target_notional:
        raise FundingError(
            f"The account holds {cash:,.2f} {account.currency or 'USD'} in cash; "
            f"{request.target_notional:,.2f} is needed."
        )
    portfolio = hunch_portfolio_for_take(take.uid)
    if portfolio is None:
        raise TakeStateError("The take has no portfolio yet; build it first.")
    target = _target_weights(take)
    if not target:
        raise TakeStateError("The take has no basket yet; build it first.")
    venue_assets = connector.resolve_assets(str(link.account_uid), list(target))
    missing = sorted(set(target) - set(venue_assets))
    if missing:
        raise FundingError(
            f"The venue cannot trade {len(missing)} basket instruments: {', '.join(missing)}"
        )

    now = utc_now()
    fund = ensure_virtual_fund(
        fund_identifier(take.uid, link.account_uid), link.account_uid, portfolio.portfolio_uid
    )
    target_refs = publish_account_target(
        link.account_uid,
        portfolio_uid=portfolio.portfolio_uid,
        notional=request.target_notional,
        time_index=now,
        take_uid=take.uid,
    )
    policy = request.autopilot_policy or (
        AutopilotPolicy() if request.execution_mode == "autopilot" else None
    )
    funding = HunchFunding.upsert(
        take_uid=take.uid,
        owner_user_uid=user_uid,
        profile_account_uid=link.uid,
        venue=link.venue,
        virtual_fund_uid=fund.uid,
        target_notional=float(request.target_notional),
        currency=account.currency or CASH_ASSET_IDENTIFIER,
        status="pending_initial",
        autopilot_policy_json=policy.model_dump() if policy else None,
        created_at=now,
        updated_at=now,
        activated_at=None,
        closed_at=None,
        metadata_json={
            "account_uid": str(link.account_uid),
            "account_identifier": account.unique_identifier,
            "execution_capability": connector.execution_capability(),
            **target_refs,
        },
    )
    take = Take.update(
        take.uid, status="funding", execution_mode=request.execution_mode, updated_at=now
    )
    proposal = propose(
        funding, take, trigger="initial", current={}, cash_available=request.target_notional
    )
    return HunchFunding.get_by_uid(funding.uid) or funding, proposal


def propose(
    funding: HunchFunding,
    take: Take,
    *,
    trigger: str,
    current: dict[str, float],
    cash_available: float,
    target: dict[str, float] | None = None,
    review_date: dt.date | None = None,
    notify_pending: bool = True,
) -> HunchRebalanceProposal:
    """Create a proposal for the funding; autopilot takes submit it when the policy allows."""
    from hunch.portfolios.build import take_revisions

    link, connector = _link_and_connector(funding)
    target = _target_weights(take) if target is None else target
    figis = sorted(set(target) | set(_positions(current)))
    prices = _prices(figis)
    venue_assets = connector.resolve_assets(str(link.account_uid), figis)
    proposal_uid = uuid.uuid4()
    legs, notes = compute_legs(
        proposal_uid=proposal_uid,
        target=target,
        notional=funding.target_notional,
        current=current,
        prices=prices,
        venue_assets=venue_assets,
        cash_available=cash_available,
    )
    now = utc_now()
    revisions = take_revisions(take.uid)
    nav = (
        _nav({**current, CASH_ASSET_IDENTIFIER: cash_available}, prices)
        if current
        else funding.target_notional
    )
    summary = _proposal_summary(take, trigger, legs, notes, funding)
    check = None
    if take.execution_mode == "autopilot" and funding.autopilot_policy_json:
        check = autopilot_check(
            AutopilotPolicy.model_validate(funding.autopilot_policy_json),
            legs,
            nav=nav,
            current=_positions(current),
            target=target,
            now=now,
        )
    proposal = HunchRebalanceProposal.create(
        uid=proposal_uid,
        take_uid=take.uid,
        funding_uid=funding.uid,
        owner_user_uid=funding.owner_user_uid,
        revision_uid=revisions[-1].uid if revisions else None,
        trigger=trigger,
        status="proposed",
        legs_json=legs,
        summary_md=summary,
        autopilot_check_json=check,
        expires_at=next_session_close(now),
        created_at=now,
        updated_at=now,
        metadata_json={
            "notes": notes,
            "review_date": review_date.isoformat() if review_date else None,
            "venue": link.venue,
            "estimated_turnover": round(sum(l["estimated_notional"] for l in legs) / nav, 6)
            if nav
            else None,
        },
    )
    if not legs:
        proposal = HunchRebalanceProposal.update(
            proposal.uid,
            status="filled",
            completed_at=now,
            updated_at=now,
            metadata_json={**(proposal.metadata_json or {}), "no_trades": True},
        )
        if funding.status == "pending_initial":
            _activate_funding(funding, take, now)
        return proposal
    if check is not None and check["ok"]:
        return submit_proposal(proposal)
    if not notify_pending:
        return proposal
    notify(
        funding.owner_user_uid,
        "proposal_awaiting_approval",
        f"{take.title}: {len(legs)} trades await your approval",
        body_md=summary
        + (("\n\nAutopilot held back: " + "; ".join(check["reasons"])) if check else ""),
        take_uid=take.uid,
        payload={"proposal_uid": str(proposal.uid), "trigger": trigger, "legs": len(legs)},
    )
    return proposal


def _proposal_summary(
    take: Take, trigger: str, legs: list[dict[str, Any]], notes: list[str], funding: HunchFunding
) -> str:
    lines = [
        f"## Proposed trades ({trigger})",
        "",
        f"Take **{take.title}**, funded with {funding.target_notional:,.0f} {funding.currency}.",
        "",
    ]
    if not legs:
        lines.append("No trades are needed; the account already matches the basket.")
    else:
        lines.append("| Side | Ticker | Quantity | Est. price | Est. notional | Why |")
        lines.append("| --- | --- | ---: | ---: | ---: | --- |")
        for leg in legs:
            lines.append(
                f"| {leg['side']} | {leg['ticker']} | {leg['quantity']:g} | {leg['estimated_price']:,.2f} | "
                f"{leg['estimated_notional']:,.2f} | {leg['reason']} |"
            )
    if notes:
        lines.append("")
        lines.extend(f"- {note}" for note in notes)
    lines.append("")
    lines.append("Estimates use the last stored close; fills happen at market prices.")
    return "\n".join(lines)


# -- approvals and execution --------------------------------------------------------------------


def approve_proposal(user_uid: str, proposal_uid: uuid.UUID | str) -> HunchRebalanceProposal:
    proposal = owned_proposal(user_uid, proposal_uid)
    if proposal.status != "proposed":
        raise FundingError(
            f"The proposal is {proposal.status}; only proposed trades can be approved."
        )
    now = utc_now()
    if proposal.expires_at is not None and proposal.expires_at < now:
        HunchRebalanceProposal.update(proposal.uid, status="expired", updated_at=now)
        raise FundingError("The proposal expired; ask for a fresh one.")
    proposal = HunchRebalanceProposal.update(
        proposal.uid,
        status="approved",
        decided_by_user_uid=user_uid,
        decided_at=now,
        updated_at=now,
    )
    return submit_proposal(proposal)


def reject_proposal(
    user_uid: str, proposal_uid: uuid.UUID | str, *, reason: str | None = None
) -> HunchRebalanceProposal:
    proposal = owned_proposal(user_uid, proposal_uid)
    if proposal.status not in ("proposed", "approved"):
        raise FundingError(f"The proposal is {proposal.status} and cannot be rejected.")
    now = utc_now()
    updated = HunchRebalanceProposal.update(
        proposal.uid,
        status="rejected",
        decided_by_user_uid=user_uid,
        decided_at=now,
        updated_at=now,
        metadata_json={**(proposal.metadata_json or {}), "rejection_reason": reason},
    )
    funding = HunchFunding.get_by_uid(proposal.funding_uid)
    if (
        funding is not None
        and funding.status == "pending_initial"
        and proposal.trigger == "initial"
    ):
        _close_funding(funding, status="failed", now=now, reason="initial trades rejected")
    return updated


def _order_legs(proposal: HunchRebalanceProposal) -> list[OrderLeg]:
    return [
        OrderLeg(
            client_order_id=leg["client_order_id"],
            figi=leg["figi"],
            asset_identifier=leg["asset_identifier"],
            symbol=leg["ticker"],
            side=leg["side"],
            quantity=float(leg["quantity"]),
            estimated_price=leg.get("estimated_price"),
        )
        for leg in proposal.legs_json
    ]


def submit_proposal(proposal: HunchRebalanceProposal) -> HunchRebalanceProposal:
    """Hand the legs to the venue connector (automatic) or to the person (manual venues)."""
    funding = HunchFunding.get_by_uid(proposal.funding_uid)
    take = Take.get_by_uid(proposal.take_uid)
    if funding is None or take is None:
        raise FundingError("The proposal's funding or take no longer exists.")
    link, connector = _link_and_connector(funding)
    now = utc_now()
    capability = connector.execution_capability()
    batch_id = f"HUNCH_BATCH__{proposal.uid.hex}"
    if capability == "manual":
        updated = HunchRebalanceProposal.update(
            proposal.uid,
            status="approved",
            updated_at=now,
            metadata_json={
                **(proposal.metadata_json or {}),
                "manual_execution": True,
                "batch_id": batch_id,
            },
        )
        notify(
            funding.owner_user_uid,
            "proposal_awaiting_approval",
            f"{take.title}: place these orders at your broker",
            body_md=proposal.summary_md
            + "\n\nThis venue executes manually: place the orders yourself; "
            "the next holdings capture reconciles the take.",
            take_uid=take.uid,
            payload={"proposal_uid": str(proposal.uid), "manual": True},
        )
        return updated
    if capability != "automatic":
        raise ConnectorCapabilityUnavailable(
            f"The {link.venue} connector cannot execute orders yet."
        )
    # The batch is Hunch's identifier of this execution; the venue's connector keeps the
    # execution ledger (orders, trades and any order batch) on its side (ADR 0006).
    try:
        result = connector.submit_orders(str(link.account_uid), batch_id, _order_legs(proposal))
    except ConnectorError as exc:
        failed = HunchRebalanceProposal.update(
            proposal.uid,
            status="failed",
            completed_at=now,
            updated_at=now,
            metadata_json={
                **(proposal.metadata_json or {}),
                "batch_id": batch_id,
                "error": str(exc),
                "error_code": exc.code,
            },
        )
        notify(
            funding.owner_user_uid,
            "proposal_failed",
            f"{take.title}: the trades were not accepted",
            body_md=str(exc),
            take_uid=take.uid,
            payload={"proposal_uid": str(proposal.uid), "code": exc.code},
        )
        if funding.status == "pending_initial":
            _close_funding(funding, status="failed", now=now, reason=str(exc))
        return failed
    submitted = HunchRebalanceProposal.update(
        proposal.uid,
        status="submitted",
        submitted_at=now,
        updated_at=now,
        metadata_json={
            **(proposal.metadata_json or {}),
            "batch_id": batch_id,
            "accepted": result.accepted,
            "submission_message": result.message,
        },
    )
    return sync_proposal(submitted, states=result.orders)


def sync_proposal(
    proposal: HunchRebalanceProposal, *, states: list[OrderState] | None = None
) -> HunchRebalanceProposal:
    """Pull order states from the venue, book fills into the virtual fund, settle the proposal."""
    if proposal.status not in ("submitted", "partially_filled"):
        return proposal
    funding = HunchFunding.get_by_uid(proposal.funding_uid)
    take = Take.get_by_uid(proposal.take_uid)
    if funding is None or take is None:
        return proposal
    link, connector = _link_and_connector(funding)
    batch_id = (proposal.metadata_json or {}).get("batch_id") or f"HUNCH_BATCH__{proposal.uid.hex}"
    if states is None:
        states = connector.sync_orders(str(link.account_uid), batch_id)
    if not states:
        return proposal
    now = utc_now()
    metadata = dict(proposal.metadata_json or {})
    applied: dict[str, float] = dict(metadata.get("applied_fills") or {})
    legs_by_id = {leg["client_order_id"]: leg for leg in proposal.legs_json}
    _, state = _fund_state(funding)
    fund = dict(state)
    if not state and funding.status == "pending_initial":
        fund[CASH_ASSET_IDENTIFIER] = float(funding.target_notional)
    new_fills = False
    for order in states:
        leg = legs_by_id.get(order.client_order_id)
        if leg is None:
            continue
        already = applied.get(order.client_order_id, 0.0)
        delta = order.filled_quantity - already
        if delta <= 1e-9:
            continue
        signed = delta if leg["side"] == "buy" else -delta
        price = float(order.average_fill_price or leg.get("estimated_price") or 0.0)
        fund[leg["figi"]] = fund.get(leg["figi"], 0.0) + signed
        fund[CASH_ASSET_IDENTIFIER] = fund.get(CASH_ASSET_IDENTIFIER, 0.0) - signed * price
        applied[order.client_order_id] = order.filled_quantity
        new_fills = True
    if new_fills and funding.virtual_fund_uid is not None:
        snapshot = connector.latest_holdings(str(link.account_uid)) or connector.capture_holdings(
            str(link.account_uid)
        )
        allocations = [
            {
                "asset_identifier": asset,
                "quantity": qty,
                "extra_details": {"proposal_uid": str(proposal.uid)},
            }
            for asset, qty in fund.items()
            if abs(qty) > 1e-9 and (asset != CASH_ASSET_IDENTIFIER or qty > 0.005)
        ]
        write_fund_holdings(
            funding.virtual_fund_uid,
            source_account_holdings_set_uid=snapshot.holdings_set_uid or uuid.uuid4(),
            time_index=snapshot.time_index,
            allocations=allocations,
        )
    terminal = all(order.terminal for order in states)
    filled_all = all(order.filled for order in states) and len(states) >= len(legs_by_id)
    any_fill = any(order.filled_quantity > 0 for order in states)
    status = proposal.status
    if terminal:
        status = "filled" if filled_all else ("partially_filled" if any_fill else "failed")
    elif any_fill:
        status = "partially_filled"
    metadata.update(
        {
            "applied_fills": applied,
            "orders": [
                {
                    "client_order_id": o.client_order_id,
                    "status": o.status,
                    "filled_quantity": o.filled_quantity,
                    "average_fill_price": o.average_fill_price,
                    "broker_order_id": o.broker_order_id,
                }
                for o in states
            ],
            "last_sync_at": now.isoformat(),
        }
    )
    updated = HunchRebalanceProposal.update(
        proposal.uid,
        status=status,
        updated_at=now,
        completed_at=now if terminal else None,
        metadata_json=metadata,
    )
    if terminal:
        if status == "failed":
            notify(
                funding.owner_user_uid,
                "proposal_failed",
                f"{take.title}: no order was filled",
                body_md=proposal.summary_md,
                take_uid=take.uid,
                payload={"proposal_uid": str(proposal.uid)},
            )
            if funding.status == "pending_initial":
                _close_funding(funding, status="failed", now=now, reason="no fill")
        else:
            notify(
                funding.owner_user_uid,
                "proposal_executed",
                f"{take.title}: {sum(1 for o in states if o.filled_quantity > 0)} orders filled",
                body_md=proposal.summary_md,
                take_uid=take.uid,
                payload={"proposal_uid": str(proposal.uid), "status": status},
            )
            if proposal.trigger == "withdrawal":
                _close_funding(funding, status="closed", now=now, reason="withdrawn")
            elif funding.status == "pending_initial":
                _activate_funding(funding, take, now)
    return updated


def _activate_funding(funding: HunchFunding, take: Take, now: dt.datetime) -> None:
    HunchFunding.update(funding.uid, status="active", activated_at=now, updated_at=now)
    Take.update(take.uid, status="active_funded", updated_at=now)
    notify(
        funding.owner_user_uid,
        "funding_active",
        f"{take.title} is live in your {funding.venue} account",
        body_md=f"{funding.target_notional:,.0f} {funding.currency} now follows the take's basket.",
        take_uid=take.uid,
        payload={"funding_uid": str(funding.uid)},
    )


def _close_funding(funding: HunchFunding, *, status: str, now: dt.datetime, reason: str) -> None:
    HunchFunding.update(
        funding.uid,
        status=status,
        closed_at=now,
        updated_at=now,
        metadata_json={**(funding.metadata_json or {}), "closed_reason": reason},
    )
    take = Take.get_by_uid(funding.take_uid)
    if take is not None and take.status in ("funding", "active_funded"):
        Take.update(
            take.uid,
            status="active_practice" if take.activated_at else "built",
            execution_mode="practice",
            updated_at=now,
        )
        notify(
            funding.owner_user_uid,
            "funding_closed",
            f"{take.title}: funding {status}",
            body_md=reason,
            take_uid=take.uid,
            payload={"funding_uid": str(funding.uid), "status": status},
        )


# -- reviews, withdrawal, scheduled sync --------------------------------------------------------


def proposal_from_review(
    *, take: Take, drift: dict[str, Any], trigger: str, review_date: dt.date
) -> HunchRebalanceProposal | None:
    funding = active_funding_for_take(take.uid)
    if funding is None or funding.status != "active":
        return None
    if open_proposals_for_take(take.uid):
        return None
    _, state = _fund_state(funding)
    return propose(
        funding,
        take,
        trigger=trigger,
        current=_positions(state),
        cash_available=float(state.get(CASH_ASSET_IDENTIFIER, 0.0)),
        review_date=review_date,
    )


def withdraw_take(user_uid: str, take_uid: uuid.UUID | str) -> HunchRebalanceProposal:
    """Sell the funded positions back to cash; the person's request is the approval."""
    take = owned_take(user_uid, take_uid)
    funding = active_funding_for_take(take.uid)
    if funding is None:
        raise FundingError("The take is not funded.")
    if open_proposals_for_take(take.uid):
        raise FundingError("A proposal is still open; wait for it to settle or reject it first.")
    now = utc_now()
    HunchFunding.update(funding.uid, status="withdrawing", updated_at=now)
    funding = HunchFunding.get_by_uid(funding.uid) or funding
    _, state = _fund_state(funding)
    positions = _positions(state)
    if not positions:
        _close_funding(funding, status="closed", now=now, reason="withdrawn (no positions)")
        return propose(
            funding, take, trigger="withdrawal", current={}, cash_available=0.0, target={}
        )
    proposal = propose(
        funding,
        take,
        trigger="withdrawal",
        current=positions,
        cash_available=float(state.get(CASH_ASSET_IDENTIFIER, 0.0)),
        target={},
        notify_pending=False,
    )
    if proposal.status == "proposed":
        proposal = HunchRebalanceProposal.update(
            proposal.uid,
            status="approved",
            decided_by_user_uid=user_uid,
            decided_at=now,
            updated_at=now,
        )
        proposal = submit_proposal(proposal)
    return proposal


def sync_open_proposals() -> list[HunchRebalanceProposal]:
    rows = HunchRebalanceProposal.filter(limit=5000)
    synced = []
    now = utc_now()
    for row in rows:
        if row.status in ("submitted", "partially_filled"):
            synced.append(sync_proposal(row))
        elif row.status == "proposed" and row.expires_at is not None and row.expires_at < now:
            synced.append(HunchRebalanceProposal.update(row.uid, status="expired", updated_at=now))
    return synced


__all__ = [
    "AutopilotPolicy",
    "FundingError",
    "FundingRequest",
    "account_weights_for_take",
    "active_funding_for_take",
    "active_link",
    "approve_proposal",
    "autopilot_check",
    "compute_legs",
    "fund_summary",
    "fund_take",
    "fund_weights",
    "funding_for_take",
    "list_fundings",
    "list_proposals",
    "next_session_close",
    "open_proposals_for_take",
    "owned_funding",
    "owned_proposal",
    "propose",
    "proposal_from_review",
    "reject_proposal",
    "submit_proposal",
    "sync_open_proposals",
    "sync_proposal",
    "withdraw_take",
]
