"""Researching takes and reading the research they keep (ADR 0008).

Research is the first build step and stands on its own: the owner starts one (inline locally, the
`Hunch Take Research` Job hosted), the take keeps every result numbered, and a build constructs
the basket from one of them. Anyone who can read the take can read its research.
"""

from __future__ import annotations

import uuid

from hunch.api.app.identity import ActingUser
from hunch.api.app.schemas import ResearchResource, ResearchResponse, TakeResource
from hunch.api.app.services.takes import take_resources
from hunch.operations.builds import StartedBuild, start_take_research
from hunch.research.runs import take_research_rows
from hunch.takes import Take
from hunch.takes.research import TakeResearch
from hunch.takes.services import get_take_for, owned_take


def research_resource(row: TakeResearch) -> ResearchResource:
    return ResearchResource(
        uid=str(row.uid),
        take_uid=str(row.take_uid),
        number=row.number,
        mode=row.mode,
        brief=dict(row.brief_json or {}),
        candidates=list(row.candidates_json or []),
        rationale_md=row.rationale_md or "",
        evidence=list(row.evidence_json or []),
        provider=row.provider,
        model=row.model,
        inference_request_uids=list(row.inference_request_uids or []),
        conversation_uid=row.conversation_uid,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _take_resource(row: Take) -> TakeResource:
    return take_resources([row])[0]


def research_take_resource(
    user: ActingUser, take_uid: str, *, research_mode: str | None = None
) -> ResearchResponse:
    """Research an owned take's thesis against the universe and keep the result."""
    take = owned_take(user.uid, take_uid)
    started: StartedBuild = start_take_research(
        take.uid, research_mode=research_mode, created_by="user"
    )
    if started.execution == "inline" and started.result is not None:
        return ResearchResponse(
            execution="inline",
            take=_take_resource(started.result.take),
            research=research_resource(started.result.research),
        )
    return ResearchResponse(
        execution="job", take=_take_resource(take), job_run_uid=started.job_run_uid
    )


def take_research_resources(
    user: ActingUser, take_uid: str, *, limit: int = 30
) -> list[ResearchResource]:
    """The take's research, latest first."""
    take = get_take_for(user.uid, take_uid)
    rows = take_research_rows(take.uid)
    return [research_resource(row) for row in reversed(rows)][:limit]


def get_take_research_resource(
    user: ActingUser, take_uid: str, research_uid: str
) -> ResearchResource:
    take = get_take_for(user.uid, take_uid)
    try:
        uid = uuid.UUID(str(research_uid))
    except ValueError:
        uid = None
    row = TakeResearch.get_by_uid(uid) if uid is not None else None
    if row is None or str(row.take_uid) != str(take.uid):
        raise LookupError(f"Research {research_uid} does not exist for this take.")
    return research_resource(row)


__all__ = [
    "get_take_research_resource",
    "research_resource",
    "research_take_resource",
    "take_research_resources",
]
