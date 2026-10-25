"""Fundings and proposals of the acting user."""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..errors import api_http_error
from ..identity import acting_user
from ..schemas import FundingResource, ProposalDecisionRequest, ProposalResource
from ..services.fundings import (
    approve_proposal_resource,
    get_funding_resource,
    get_proposal_resource,
    list_funding_resources,
    list_proposal_resources,
    reject_proposal_resource,
    sync_proposal_resource,
)

fundings_router = APIRouter(prefix="/v1/fundings", tags=["Fundings"])
proposals_router = APIRouter(prefix="/v1/proposals", tags=["Proposals"])


@fundings_router.get("", response_model=list[FundingResource], summary="My fundings")
def list_fundings() -> list[FundingResource]:
    try:
        return list_funding_resources(acting_user())
    except Exception as exc:
        raise api_http_error(exc) from exc


@fundings_router.get("/{funding_uid}", response_model=FundingResource, summary="One funding")
def get_funding(funding_uid: str) -> FundingResource:
    try:
        return get_funding_resource(acting_user(), funding_uid)
    except Exception as exc:
        raise api_http_error(exc) from exc


@proposals_router.get("", response_model=list[ProposalResource], summary="My proposals")
def list_proposals(
    status: str | None = Query(default=None),
    take_uid: str | None = Query(default=None),
    open_only: bool = Query(default=False),
) -> list[ProposalResource]:
    try:
        return list_proposal_resources(
            acting_user(), status=status, take_uid=take_uid, open_only=open_only
        )
    except Exception as exc:
        raise api_http_error(exc) from exc


@proposals_router.get("/{proposal_uid}", response_model=ProposalResource, summary="One proposal")
def get_proposal(proposal_uid: str) -> ProposalResource:
    try:
        return get_proposal_resource(acting_user(), proposal_uid)
    except Exception as exc:
        raise api_http_error(exc) from exc


@proposals_router.post(
    "/{proposal_uid}/actions/approve",
    response_model=ProposalResource,
    summary="Approve the trades",
    description="Approve a proposed rebalance; the venue connector executes it.",
)
def approve(proposal_uid: str) -> ProposalResource:
    try:
        return approve_proposal_resource(acting_user(), proposal_uid)
    except Exception as exc:
        raise api_http_error(exc) from exc


@proposals_router.post(
    "/{proposal_uid}/actions/reject", response_model=ProposalResource, summary="Reject the trades"
)
def reject(proposal_uid: str, payload: ProposalDecisionRequest | None = None) -> ProposalResource:
    try:
        return reject_proposal_resource(
            acting_user(), proposal_uid, reason=payload.reason if payload else None
        )
    except Exception as exc:
        raise api_http_error(exc) from exc


@proposals_router.post(
    "/{proposal_uid}/actions/sync",
    response_model=ProposalResource,
    summary="Refresh order states",
    description="Pull order states from the venue and book fills into the take's fund.",
)
def sync(proposal_uid: str) -> ProposalResource:
    try:
        return sync_proposal_resource(acting_user(), proposal_uid)
    except Exception as exc:
        raise api_http_error(exc) from exc
