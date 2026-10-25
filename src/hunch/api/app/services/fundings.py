"""Fundings and proposals as the REST routes and the MCP tools present them."""

from __future__ import annotations

import uuid

from hunch.api.app.identity import ActingUser
from hunch.api.app.schemas import (
    AutopilotPolicyResource,
    FundingResource,
    FundPositionResource,
    FundRequest,
    FundResponse,
    ProposalLegResource,
    ProposalResource,
)
from hunch.funding import HunchFunding, HunchRebalanceProposal
from hunch.funding.services import (
    AutopilotPolicy,
    FundingRequest,
    approve_proposal,
    fund_summary,
    fund_take,
    funding_for_take,
    list_fundings,
    list_proposals,
    owned_funding,
    owned_proposal,
    reject_proposal,
    sync_proposal,
    withdraw_take,
)
from hunch.takes import Take
from hunch.takes.services import owned_take

LIVE_FUNDING_STATUSES = ("pending_initial", "active", "withdrawing")


def _take_title(take_uid: uuid.UUID, cache: dict[uuid.UUID, Take | None]) -> Take | None:
    if take_uid not in cache:
        cache[take_uid] = Take.get_by_uid(take_uid)
    return cache[take_uid]


def funding_resource(
    funding: HunchFunding, *, take: Take | None = None, with_summary: bool = True
) -> FundingResource:
    take = take or Take.get_by_uid(funding.take_uid)
    summary = (
        fund_summary(funding) if with_summary and funding.status in LIVE_FUNDING_STATUSES else {}
    )
    policy = funding.autopilot_policy_json
    metadata = funding.metadata_json or {}
    return FundingResource(
        uid=str(funding.uid),
        take_uid=str(funding.take_uid),
        take_title=take.title if take else None,
        profile_account_uid=str(funding.profile_account_uid),
        venue=funding.venue,
        status=funding.status,
        target_notional=funding.target_notional,
        currency=funding.currency,
        execution_mode=take.execution_mode if take else None,
        autopilot_policy=AutopilotPolicyResource.model_validate(policy) if policy else None,
        execution_capability=metadata.get("execution_capability"),
        nav=summary.get("nav"),
        cash=summary.get("cash"),
        invested=summary.get("invested"),
        return_on_notional=summary.get("return_on_notional"),
        as_of=summary.get("as_of"),
        positions=[
            FundPositionResource.model_validate(item) for item in summary.get("positions", [])
        ],
        created_at=funding.created_at,
        activated_at=funding.activated_at,
        closed_at=funding.closed_at,
    )


def proposal_resource(
    proposal: HunchRebalanceProposal, *, take: Take | None = None
) -> ProposalResource:
    take = take or Take.get_by_uid(proposal.take_uid)
    metadata = proposal.metadata_json or {}
    return ProposalResource(
        uid=str(proposal.uid),
        take_uid=str(proposal.take_uid),
        take_title=take.title if take else None,
        funding_uid=str(proposal.funding_uid),
        trigger=proposal.trigger,
        status=proposal.status,
        legs=[ProposalLegResource.model_validate(leg) for leg in proposal.legs_json],
        summary_md=proposal.summary_md,
        estimated_turnover=metadata.get("estimated_turnover"),
        autopilot_check=proposal.autopilot_check_json,
        manual_execution=bool(metadata.get("manual_execution")),
        expires_at=proposal.expires_at,
        decided_at=proposal.decided_at,
        submitted_at=proposal.submitted_at,
        completed_at=proposal.completed_at,
        created_at=proposal.created_at,
        orders=list(metadata.get("orders") or []),
        notes=list(metadata.get("notes") or []),
    )


def fund_take_resource(user: ActingUser, take_uid: str, request: FundRequest) -> FundResponse:
    policy = request.autopilot_policy
    funding, proposal = fund_take(
        user.uid,
        take_uid,
        FundingRequest(
            profile_account_uid=uuid.UUID(request.profile_account_uid),
            target_notional=request.target_notional,
            execution_mode=request.execution_mode,
            autopilot_policy=AutopilotPolicy.model_validate(policy.model_dump())
            if policy
            else None,
        ),
    )
    take = Take.get_by_uid(funding.take_uid)
    return FundResponse(
        funding=funding_resource(funding, take=take),
        proposal=proposal_resource(proposal, take=take),
    )


def withdraw_take_resource(user: ActingUser, take_uid: str) -> ProposalResource:
    return proposal_resource(withdraw_take(user.uid, take_uid))


def take_funding_resource(user: ActingUser, take_uid: str) -> FundingResource:
    take = owned_take(user.uid, take_uid)
    funding = funding_for_take(take.uid)
    if funding is None:
        raise LookupError("The take is not funded.")
    return funding_resource(funding, take=take)


def list_funding_resources(user: ActingUser) -> list[FundingResource]:
    cache: dict[uuid.UUID, Take | None] = {}
    return [
        funding_resource(row, take=_take_title(row.take_uid, cache))
        for row in list_fundings(user.uid)
    ]


def get_funding_resource(user: ActingUser, funding_uid: str) -> FundingResource:
    return funding_resource(owned_funding(user.uid, funding_uid))


def list_proposal_resources(
    user: ActingUser,
    *,
    status: str | None = None,
    take_uid: str | None = None,
    open_only: bool = False,
) -> list[ProposalResource]:
    cache: dict[uuid.UUID, Take | None] = {}
    rows = list_proposals(user.uid, status=status, take_uid=take_uid, open_only=open_only)
    return [proposal_resource(row, take=_take_title(row.take_uid, cache)) for row in rows]


def get_proposal_resource(user: ActingUser, proposal_uid: str) -> ProposalResource:
    return proposal_resource(owned_proposal(user.uid, proposal_uid))


def approve_proposal_resource(user: ActingUser, proposal_uid: str) -> ProposalResource:
    return proposal_resource(approve_proposal(user.uid, proposal_uid))


def reject_proposal_resource(
    user: ActingUser, proposal_uid: str, *, reason: str | None = None
) -> ProposalResource:
    return proposal_resource(reject_proposal(user.uid, proposal_uid, reason=reason))


def sync_proposal_resource(user: ActingUser, proposal_uid: str) -> ProposalResource:
    return proposal_resource(sync_proposal(owned_proposal(user.uid, proposal_uid)))


__all__ = [
    "approve_proposal_resource",
    "fund_take_resource",
    "funding_resource",
    "get_funding_resource",
    "get_proposal_resource",
    "list_funding_resources",
    "list_proposal_resources",
    "proposal_resource",
    "reject_proposal_resource",
    "sync_proposal_resource",
    "take_funding_resource",
    "withdraw_take_resource",
]
