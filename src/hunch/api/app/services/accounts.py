"""Linked venue accounts as the REST routes and the MCP tools present them."""

from __future__ import annotations

import uuid

from hunch.api.app.identity import ActingUser
from hunch.api.app.schemas import (
    HoldingResource,
    HoldingsSnapshotResource,
    LinkAccountRequest,
    LinkedAccountResource,
)
from hunch.connectors import HoldingsSnapshot
from hunch.profiles import HunchUserProfileAccount
from hunch.profiles.accounts import (
    candidate_accounts,
    link_account,
    link_holdings,
    link_payload,
    list_links,
    owned_link,
    revoke_link,
    start_link,
)


def linked_account_resource(
    link: HunchUserProfileAccount, *, live: bool = True
) -> LinkedAccountResource:
    account = link_account(link) if live and link.status != "revoked" else None
    return LinkedAccountResource(**link_payload(link, account))


def list_linked_accounts(
    user: ActingUser, *, include_revoked: bool = False
) -> list[LinkedAccountResource]:
    return [
        linked_account_resource(link)
        for link in list_links(user.uid, include_revoked=include_revoked)
    ]


def get_linked_account(user: ActingUser, link_uid: str) -> LinkedAccountResource:
    return linked_account_resource(owned_link(user.uid, link_uid))


def link_account_resource(user: ActingUser, request: LinkAccountRequest) -> LinkedAccountResource:
    link = start_link(
        user.uid,
        request.venue,
        account_uid=request.account_uid,
        account_name=request.account_name,
        username=user.username,
    )
    return linked_account_resource(link)


def revoke_linked_account(user: ActingUser, link_uid: str) -> LinkedAccountResource:
    return linked_account_resource(revoke_link(user.uid, link_uid), live=False)


def linkable_accounts(user: ActingUser, venue: str) -> list[dict[str, object]]:
    return [
        {
            "account_uid": account.account_uid,
            "unique_identifier": account.unique_identifier,
            "account_name": account.account_name,
            "is_paper": account.is_paper,
            "status": account.status,
            "cash": account.cash,
            "equity": account.equity,
        }
        for account in candidate_accounts(user.uid, venue)
    ]


def holdings_resource(snapshot: HoldingsSnapshot) -> HoldingsSnapshotResource:
    return HoldingsSnapshotResource(
        account_uid=snapshot.account_uid,
        time_index=snapshot.time_index,
        holdings_set_uid=snapshot.holdings_set_uid,
        cash=round(snapshot.cash(), 2),
        holdings=[
            HoldingResource(
                asset_identifier=h.asset_identifier,
                kind=h.kind,
                quantity=h.quantity,
                direction=h.direction,
                symbol=h.symbol,
                figi=h.figi,
                market_value=h.market_value,
            )
            for h in snapshot.holdings
        ],
    )


def linked_account_holdings(
    user: ActingUser, link_uid: str, *, capture: bool = False
) -> HoldingsSnapshotResource:
    link = owned_link(user.uid, link_uid)
    snapshot = link_holdings(link, capture=capture)
    if snapshot is None:
        raise LookupError("The account has no holdings snapshot yet.")
    return holdings_resource(snapshot)


def link_uid_or_404(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise LookupError("The linked account does not exist.") from exc


__all__ = [
    "get_linked_account",
    "holdings_resource",
    "link_account_resource",
    "linkable_accounts",
    "linked_account_holdings",
    "linked_account_resource",
    "list_linked_accounts",
    "revoke_linked_account",
]
