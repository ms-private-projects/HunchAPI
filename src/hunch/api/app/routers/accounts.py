"""Linked venue accounts of the acting user."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query

from ..errors import api_http_error
from ..identity import acting_user
from ..schemas import HoldingsSnapshotResource, LinkAccountRequest, LinkedAccountResource
from ..services.accounts import (
    get_linked_account,
    link_account_resource,
    linkable_accounts,
    linked_account_holdings,
    list_linked_accounts,
    revoke_linked_account,
)

router = APIRouter(prefix="/v1/profile/accounts", tags=["Linked accounts"])


@router.get("", response_model=list[LinkedAccountResource], summary="My linked accounts")
def list_accounts(include_revoked: bool = Query(default=False)) -> list[LinkedAccountResource]:
    try:
        return list_linked_accounts(acting_user(), include_revoked=include_revoked)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.get(
    "/linkable",
    summary="Accounts I could link",
    description="Accounts the venue connector registered for me that are not linked yet.",
)
def list_linkable(venue: Literal["alpaca", "ibkr"] = Query(...)) -> list[dict[str, object]]:
    try:
        return linkable_accounts(acting_user(), venue)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.post(
    "/actions/link",
    response_model=LinkedAccountResource,
    status_code=201,
    summary="Link a venue account",
    description=(
        "Link an account the venue connector created for me. Credentials never pass through "
        "Hunch: they are entered on the connector. In simulated mode a paper account is created."
    ),
)
def link(payload: LinkAccountRequest) -> LinkedAccountResource:
    try:
        return link_account_resource(acting_user(), payload)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.get("/{link_uid}", response_model=LinkedAccountResource, summary="One linked account")
def get_link(link_uid: str) -> LinkedAccountResource:
    try:
        return get_linked_account(acting_user(), link_uid)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.post(
    "/{link_uid}/actions/revoke",
    response_model=LinkedAccountResource,
    summary="Revoke a link",
    description="Stop using the account in Hunch; funded takes in it must be withdrawn first.",
)
def revoke(link_uid: str) -> LinkedAccountResource:
    try:
        return revoke_linked_account(acting_user(), link_uid)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.get(
    "/{link_uid}/holdings",
    response_model=HoldingsSnapshotResource,
    summary="Latest holdings of a linked account",
)
def holdings(link_uid: str, capture: bool = Query(default=False)) -> HoldingsSnapshotResource:
    try:
        return linked_account_holdings(acting_user(), link_uid, capture=capture)
    except Exception as exc:
        raise api_http_error(exc) from exc
