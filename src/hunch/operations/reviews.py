"""Run a daily review with the funding hooks wired in (practice and funded takes alike)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from hunch.reviews import HunchDailyReview
from hunch.reviews.services import review_take


def run_review(
    take_uid: uuid.UUID | str,
    *,
    review_date: dt.date | None = None,
    mode: str | None = None,
) -> HunchDailyReview:
    """Review one take; funded takes get their account weights and the proposal hook."""
    from hunch.funding.services import account_weights_for_take, proposal_from_review

    current: dict[str, float] | None = account_weights_for_take(take_uid)
    hook: Any = proposal_from_review if current is not None else None
    return review_take(
        take_uid,
        review_date=review_date,
        mode=mode,
        current_weights=current,
        proposal_factory=hook,
    )


__all__ = ["run_review"]
