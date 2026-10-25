"""Linking venue accounts to a Hunch user.

A link records which connector-created ``Account`` belongs to which Hunch user. The connector
keeps the broker credentials; Hunch verifies ownership against what the connector reports
(``credentials_updated_by_user_uid`` at Alpaca; the simulated venue records its owner) and refuses
to link an account that another Hunch user already linked. Venues that cannot report an owner
(Interactive Brokers today) link with ``ownership_verified: false``, which the site shows.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from hunch.community.notifications import notify
from hunch.connectors import HoldingsSnapshot, VenueAccount, connector_for
from hunch.connectors.base import ConnectorError
from hunch.profiles import HunchUserProfileAccount, utc_now
from hunch.profiles.services import ensure_profile
from hunch.settings import VENUES, connector_mode

UTC = dt.timezone.utc


class LinkError(ValueError):
    """A linking rule refused the request (HTTP 409)."""


def list_links(user_uid: str, *, include_revoked: bool = False) -> list[HunchUserProfileAccount]:
    rows = HunchUserProfileAccount.filter(user_uid=user_uid, limit=500)
    if not include_revoked:
        rows = [row for row in rows if row.status != "revoked"]
    return sorted(
        rows, key=lambda row: row.linked_at or dt.datetime.min.replace(tzinfo=UTC), reverse=True
    )


def owned_link(user_uid: str, link_uid: uuid.UUID | str) -> HunchUserProfileAccount:
    link = HunchUserProfileAccount.get_by_uid(uuid.UUID(str(link_uid)))
    if link is None or link.user_uid != user_uid:
        raise LookupError("The linked account does not exist.")
    return link


def candidate_accounts(user_uid: str, venue: str) -> list[VenueAccount]:
    """Accounts the connector reports for this person that are not linked yet."""
    connector = connector_for(venue)
    linked = {
        str(row.account_uid)
        for row in HunchUserProfileAccount.filter(venue=venue, limit=5000)
        if row.status != "revoked"
    }
    accounts = connector.list_accounts(owner_user_uid=user_uid)
    return [
        account for account in accounts if account.account_uid not in linked and account.is_active
    ]


def start_link(
    user_uid: str,
    venue: str,
    *,
    account_uid: str | None = None,
    account_name: str | None = None,
    username: str | None = None,
) -> HunchUserProfileAccount:
    """Link one venue account; in simulated mode, create a paper account when none is given."""
    if venue not in VENUES:
        raise LinkError(f"Unknown venue {venue!r}.")
    ensure_profile(user_uid, username=username)
    connector = connector_for(venue)
    if account_uid is None:
        if connector_mode() == "simulated":
            account = connector.create_account(user_uid, account_name=account_name)  # type: ignore[attr-defined]
        else:
            candidates = candidate_accounts(user_uid, venue)
            if len(candidates) != 1:
                raise LinkError(
                    "Register the account on the connector first, then link it by its account_uid."
                    if not candidates
                    else "Several accounts match; pass the account_uid to link."
                )
            account = candidates[0]
    else:
        account = connector.get_account(account_uid)
        if account is None:
            raise LookupError("The connector does not know this account.")
    if not account.is_active:
        raise LinkError("The account is not active at the connector.")
    verified = True
    if account.ownership_verifiable:
        if account.owner_user_uid != user_uid:
            raise LinkError("The connector registered this account for another person.")
    else:
        verified = False
    existing = HunchUserProfileAccount.filter(account_uid=uuid.UUID(account.account_uid))
    for row in existing:
        if row.user_uid != user_uid and row.status != "revoked":
            raise LinkError("Another Hunch user already linked this account.")
    now = utc_now()
    link = HunchUserProfileAccount.upsert(
        account_uid=uuid.UUID(account.account_uid),
        user_uid=user_uid,
        venue=venue,
        is_paper=account.is_paper,
        status="active",
        linked_at=now,
        activated_at=now,
        revoked_at=None,
        metadata_json={
            "account_identifier": account.unique_identifier,
            "account_name": account.account_name,
            "external_account_id": account.external_account_id,
            "ownership_verified": verified,
            "simulated": bool(account.raw.get("metadata_json", {}).get("simulated"))
            if account.raw
            else False,
            "currency": account.currency,
        },
    )
    notify(
        user_uid,
        "account_linked",
        f"{venue.upper()} account linked" + (" (paper)" if account.is_paper else ""),
        body_md=f"`{account.unique_identifier}` is now available for funding takes.",
        payload={"link_uid": str(link.uid), "venue": venue, "ownership_verified": verified},
    )
    return link


def revoke_link(user_uid: str, link_uid: uuid.UUID | str) -> HunchUserProfileAccount:
    from hunch.funding import HunchFunding

    link = owned_link(user_uid, link_uid)
    if link.status == "revoked":
        return link
    open_fundings = [
        row
        for row in HunchFunding.filter(profile_account_uid=link.uid, limit=500)
        if row.status not in ("closed", "failed")
    ]
    if open_fundings:
        raise LinkError("Withdraw the funded takes in this account before revoking the link.")
    now = utc_now()
    return HunchUserProfileAccount.update(link.uid, status="revoked", revoked_at=now)


def link_account(link: HunchUserProfileAccount) -> VenueAccount | None:
    try:
        return connector_for(link.venue).get_account(str(link.account_uid))
    except ConnectorError:
        return None


def link_holdings(
    link: HunchUserProfileAccount, *, capture: bool = False
) -> HoldingsSnapshot | None:
    connector = connector_for(link.venue)
    if capture:
        return connector.capture_holdings(str(link.account_uid))
    return connector.latest_holdings(str(link.account_uid))


def link_payload(
    link: HunchUserProfileAccount, account: VenueAccount | None = None
) -> dict[str, Any]:
    metadata = link.metadata_json or {}
    return {
        "uid": str(link.uid),
        "venue": link.venue,
        "account_uid": str(link.account_uid),
        "account_identifier": metadata.get("account_identifier"),
        "account_name": (account.account_name if account else None) or metadata.get("account_name"),
        "is_paper": link.is_paper,
        "status": link.status,
        "ownership_verified": bool(metadata.get("ownership_verified", True)),
        "simulated": bool(metadata.get("simulated")),
        "currency": (account.currency if account else None) or metadata.get("currency") or "USD",
        "equity": account.equity if account else None,
        "cash": account.cash if account else None,
        "linked_at": link.linked_at,
        "revoked_at": link.revoked_at,
    }


__all__ = [
    "LinkError",
    "candidate_accounts",
    "link_account",
    "link_holdings",
    "link_payload",
    "list_links",
    "owned_link",
    "revoke_link",
    "start_link",
]
