"""Run a daily review with the funding hooks wired in, and dispatch the scheduled sweep as Jobs.

A review a person or the Agent asks for runs in the calling process (`run_review`). The scheduled
sweep before the US open runs in the review dispatcher Job, which holds no model credential: with
`HUNCH_REVIEW_DISPATCH=job` it starts one `Hunch Daily Review` Job run per active take instead
(`dispatch_reviews`), so every thesis check runs on that Job's model role and the takes are
reviewed in parallel. Runs start in small batches and each batch is followed to its end before
the next starts, because the platform admits four recorded model calls per Organization at once
and a person's own review or critique must keep a slot.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from hunch.operations.builds import PENDING_JOB_RUN_STATUSES
from hunch.reviews import HunchDailyReview
from hunch.reviews.services import review_take

DAILY_REVIEW_JOB_NAME = "Hunch Daily Review"
DAILY_REVIEW_JOB_PATH = "src/jobs/run_hunch_daily_review.py"

# Three runs at a time keeps one of the Organization's four recorded-inference slots free.
REVIEW_DISPATCH_BATCH_SIZE = 3
REVIEW_DISPATCH_POLL_SECONDS = 20.0
# A review Job run starts in about a minute and reviews in a few more; the dispatcher gives a
# batch half an hour before it reports the stragglers as timed out and moves on.
REVIEW_DISPATCH_BATCH_TIMEOUT_SECONDS = 1800.0
SUCCEEDED_JOB_RUN_STATUS = "SUCCEEDED"
TIMED_OUT_STATUS = "TIMED_OUT"
START_FAILED_STATUS = "START_FAILED"


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


@dataclass(slots=True)
class DispatchedReview:
    """One take's review Job run as the dispatcher saw it end."""

    take_uid: str
    job_run_uid: str | None
    status: str
    failure_summary: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == SUCCEEDED_JOB_RUN_STATUS


def start_review_job(take_uid: uuid.UUID | str, *, research_mode: str | None = None) -> str:
    """Start the review Job for one take and return its JobRun UID."""
    from hunch.operations.builds import platform_job, start_job_run

    uid = str(uuid.UUID(str(take_uid)))
    job = platform_job(DAILY_REVIEW_JOB_NAME, DAILY_REVIEW_JOB_PATH)
    args = ["--take-uid", uid]
    if research_mode:
        args += ["--research-mode", research_mode]
    return start_job_run(job, args)


def _job_run_state(job_run_uid: str) -> tuple[str | None, str | None]:
    from hunch.operations.builds import job_run_status

    found = job_run_status(job_run_uid)
    if found is None:
        return None, None
    return (str(found.get("status") or "") or None), found.get("failure_summary")


def dispatch_reviews(
    take_uids: Iterable[uuid.UUID | str],
    *,
    research_mode: str | None = None,
    batch_size: int = REVIEW_DISPATCH_BATCH_SIZE,
    poll_seconds: float = REVIEW_DISPATCH_POLL_SECONDS,
    batch_timeout_seconds: float = REVIEW_DISPATCH_BATCH_TIMEOUT_SECONDS,
    start: Callable[..., str] | None = None,
    state: Callable[[str], tuple[str | None, str | None]] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[DispatchedReview]:
    """Review every take as its own Job run, a batch at a time, and report how each run ended.

    A run that cannot start is reported as `START_FAILED`; one still pending when its batch's
    time is up is reported as `TIMED_OUT` and left to finish on its own. The order of the result
    is the order of the takes.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1.")
    start_run = start or start_review_job
    run_state = state or _job_run_state
    uids = [str(uuid.UUID(str(item))) for item in take_uids]
    results: list[DispatchedReview] = []
    for offset in range(0, len(uids), batch_size):
        batch = uids[offset : offset + batch_size]
        pending: dict[str, DispatchedReview] = {}
        for take_uid in batch:
            try:
                job_run_uid = start_run(take_uid, research_mode=research_mode)
            except Exception as exc:  # the platform's own errors carry request internals
                results.append(
                    DispatchedReview(take_uid, None, START_FAILED_STATUS, type(exc).__name__)
                )
                continue
            review = DispatchedReview(take_uid, job_run_uid, "PENDING")
            results.append(review)
            pending[job_run_uid] = review
        deadline = clock() + batch_timeout_seconds
        while pending:
            for job_run_uid, review in list(pending.items()):
                status, failure = run_state(job_run_uid)
                if status is None or status in PENDING_JOB_RUN_STATUSES:
                    continue
                review.status = status
                review.failure_summary = failure if status != SUCCEEDED_JOB_RUN_STATUS else None
                del pending[job_run_uid]
            if not pending:
                break
            if clock() >= deadline:
                for review in pending.values():
                    review.status = TIMED_OUT_STATUS
                    review.failure_summary = (
                        f"Still pending after {int(batch_timeout_seconds)} seconds."
                    )
                pending.clear()
                break
            sleep(poll_seconds)
    return results


__all__ = [
    "DAILY_REVIEW_JOB_NAME",
    "DAILY_REVIEW_JOB_PATH",
    "PENDING_JOB_RUN_STATUSES",
    "REVIEW_DISPATCH_BATCH_SIZE",
    "REVIEW_DISPATCH_BATCH_TIMEOUT_SECONDS",
    "REVIEW_DISPATCH_POLL_SECONDS",
    "START_FAILED_STATUS",
    "SUCCEEDED_JOB_RUN_STATUS",
    "TIMED_OUT_STATUS",
    "DispatchedReview",
    "dispatch_reviews",
    "run_review",
    "start_review_job",
]
