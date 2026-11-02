"""Building takes from their research and reading what Hunch built: revisions, weights,
performance. Research itself is ``hunch.api.app.services.research`` (ADR 0008)."""

from __future__ import annotations

from typing import Any

from hunch.api.app.identity import ActingUser
from hunch.api.app.schemas import BuildResponse, RevisionResource, TakeResource, WeightsResponse
from hunch.api.app.services.takes import take_resources
from hunch.operations.builds import StartedBuild, start_portfolio_refresh, start_take_build
from hunch.portfolios.build import (
    activate_practice,
    take_performance,
    take_revisions,
    take_weights,
)
from hunch.portfolios.metrics import performance_metrics
from hunch.takes import Take
from hunch.takes.revisions import TakeRevision
from hunch.takes.services import get_take_for, owned_take
from msm.api.http import TabularFrameResponse, build_tabular_frame


def revision_resource(row: TakeRevision) -> RevisionResource:
    research = row.research_json or {}
    return RevisionResource(
        uid=str(row.uid),
        take_uid=str(row.take_uid),
        revision=row.revision,
        research_uid=str(row.research_uid) if row.research_uid else None,
        kind=row.kind,
        rationale_md=row.rationale_md,
        weights=list(row.weights_json or []),
        cash_weight=research.get("cash_weight"),
        guardrail_notes=list(research.get("guardrail_notes") or []),
        candidates=list(research.get("candidates") or []),
        evidence=list(research.get("evidence") or []),
        created_by=row.created_by,
        inference_request_uids=list(row.inference_request_uids or []),
        signal_time_index=row.signal_time_index,
        created_at=row.created_at,
    )


def _take_resource(row: Take) -> TakeResource:
    return take_resources([row])[0]


def build_take_resource(
    user: ActingUser, take_uid: str, *, research_uid: str | None = None
) -> BuildResponse:
    """Construct the basket from a stored research (the latest by default) and build the
    portfolio; a take without research answers a conflict."""
    take = owned_take(user.uid, take_uid)
    started: StartedBuild = start_take_build(take.uid, research_uid=research_uid, created_by="user")
    if started.execution == "inline" and started.result is not None:
        return BuildResponse(
            execution="inline",
            take=_take_resource(started.result.take),
            revision=revision_resource(started.result.revision),
        )
    return BuildResponse(
        execution="job", take=_take_resource(take), job_run_uid=started.job_run_uid
    )


def activate_practice_resource(user: ActingUser, take_uid: str) -> TakeResource:
    take = owned_take(user.uid, take_uid)
    return _take_resource(activate_practice(take.uid))


def refresh_take_resource(user: ActingUser, take_uid: str) -> BuildResponse:
    take = owned_take(user.uid, take_uid)
    started = start_portfolio_refresh(take.uid)
    return BuildResponse(
        execution=started.execution, take=_take_resource(take), job_run_uid=started.job_run_uid
    )


def take_revision_resources(user: ActingUser, take_uid: str) -> list[RevisionResource]:
    take = get_take_for(user.uid, take_uid)
    return [revision_resource(row) for row in take_revisions(take.uid)]


def take_performance_frame(user: ActingUser, take_uid: str) -> TabularFrameResponse:
    take = get_take_for(user.uid, take_uid)
    rows = take_performance(take)
    return build_tabular_frame(
        rows=rows,
        columns=["time_index", "close", "return"],
        fields=[
            {"key": "time_index", "type": "datetime", "label": "Time"},
            {"key": "close", "type": "number", "label": "Value (activation = 1)"},
            {"key": "return", "type": "number", "label": "Daily return", "nullable": True},
        ],
        source={
            "kind": "hunch-take-performance",
            "id": str(take.uid),
            "label": take.title,
            "context": {
                "activated_at": take.activated_at.isoformat() if take.activated_at else None,
                "simulated": take.status != "active_funded",
                "points": len(rows),
                "metrics": performance_metrics(rows),
            },
        },
    )


def take_weights_resource(user: ActingUser, take_uid: str) -> WeightsResponse:
    take = get_take_for(user.uid, take_uid)
    items: list[dict[str, Any]] = take_weights(take)
    as_of = items[0]["time_index"] if items else None
    invested = round(sum(item["weight"] for item in items), 6)
    return WeightsResponse(
        take_uid=str(take.uid),
        as_of=as_of,
        items=items,
        invested=invested,
        cash=round(1 - invested, 6),
    )


__all__ = [
    "activate_practice_resource",
    "build_take_resource",
    "refresh_take_resource",
    "revision_resource",
    "take_performance_frame",
    "take_revision_resources",
    "take_weights_resource",
]
