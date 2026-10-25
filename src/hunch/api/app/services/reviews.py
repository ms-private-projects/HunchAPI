"""Daily reviews as the REST routes and the MCP tools present them."""

from __future__ import annotations

from hunch.api.app.identity import ActingUser
from hunch.api.app.schemas import ReviewResource
from hunch.reviews import HunchDailyReview
from hunch.reviews.services import list_reviews
from hunch.takes.services import get_take_for, owned_take


def review_resource(row: HunchDailyReview) -> ReviewResource:
    check = row.thesis_check_json or {}
    return ReviewResource(
        uid=str(row.uid),
        take_uid=str(row.take_uid),
        review_date=row.review_date,
        outcome=row.outcome,
        verdict=check.get("verdict"),
        drift=row.drift_json,
        thesis_check=row.thesis_check_json,
        proposal_uid=str(row.proposal_uid) if row.proposal_uid else None,
        summary_md=row.summary_md,
        created_at=row.created_at,
    )


def run_review_resource(
    user: ActingUser, take_uid: str, *, mode: str | None = None
) -> ReviewResource:
    from hunch.operations.reviews import run_review

    take = owned_take(user.uid, take_uid)
    return review_resource(run_review(take.uid, mode=mode))


def list_review_resources(
    user: ActingUser, take_uid: str, *, limit: int = 30
) -> list[ReviewResource]:
    take = get_take_for(user.uid, take_uid)
    return [review_resource(row) for row in list_reviews(take.uid, limit=limit)]


__all__ = ["list_review_resources", "review_resource", "run_review_resource"]
