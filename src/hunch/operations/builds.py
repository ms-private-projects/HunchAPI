"""Starting a research, a build or a refresh: inline in this process, or as a platform Job.

Research and construction are independent steps (ADR 0008), each with its own Job: `Hunch Take
Research` studies the target universe and stores a numbered research; `Hunch Take Build`
constructs the basket from a stored research and (re)builds the portfolio. Hosted, the API never
runs either in its own process: it starts the Job with the take UID and returns the JobRun to
poll. Locally there is no Job, so the step runs inline. The mode is `HUNCH_BUILD_EXECUTION`
(inline by default); nothing else differs.

A slow platform can let `run-job` outlast its deadline and still create the run; `start_job_run`
then finds that run and answers it, so a run that exists is never reported as a failed start.
"""

from __future__ import annotations

import datetime as dt
import itertools
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hunch.settings import build_execution

logger = logging.getLogger(__name__)

TAKE_RESEARCH_JOB_NAME = "Hunch Take Research"
TAKE_RESEARCH_JOB_PATH = "src/jobs/run_hunch_take_research.py"
TAKE_BUILD_JOB_NAME = "Hunch Take Build"
TAKE_BUILD_JOB_PATH = "src/jobs/run_hunch_take_build.py"
PORTFOLIO_REFRESH_JOB_NAME = "Hunch Portfolio Refresh"
PORTFOLIO_REFRESH_JOB_PATH = "src/jobs/run_hunch_portfolio_refresh.py"

# JobRun statuses that mean the run is still going; anything else is final.
PENDING_JOB_RUN_STATUSES: frozenset[str] = frozenset(
    {"PENDING", "QUEUED", "SCHEDULED", "STARTING", "RUNNING"}
)
JOB_START_TIMEOUT_SECONDS = 60
# After a start without an answer: how often, and how far apart, to look for the run it created.
# The platform lists a Job's runs newest first; the start is matched among the latest ones, and a
# run counts when it started at most `JOB_START_CLOCK_SKEW` before the request (clock skew).
JOB_START_LOOKUPS = 3
JOB_START_LOOKUP_INTERVAL_SECONDS = 10.0
JOB_START_LOOKUP_RUNS = 50
JOB_START_CLOCK_SKEW = dt.timedelta(minutes=2)


@dataclass(slots=True)
class StartedBuild:
    """One started step: the inline result, or the JobRun that runs it."""

    execution: str
    take_uid: str
    job_run_uid: str | None = None
    result: Any | None = None


def platform_job(name: str, execution_path: str) -> Any:
    """The workflow-declared Job of this branch, verified by name and execution path."""
    from mainsequence.client import Job

    matches = [job for job in Job.filter(name=name, timeout=60) if job.name == name]
    if not matches:
        raise LookupError(f"The Job {name!r} is not declared on this branch.")
    job = matches[0]
    declared_path = getattr(job, "execution_path", None)
    if declared_path and declared_path != execution_path:
        raise LookupError(f"The Job {name!r} does not run {execution_path}.")
    return job


class JobStartUnconfirmed(RuntimeError):
    """A Job start the platform did not answer, with no run of it found; it may still start."""


def started_job_run_uid(started: Any) -> str:
    """The JobRun UID from `Job.run_job`, which answers `{"message": ..., "job_run_uid": ...}`."""
    job_run_uid = started.get("job_run_uid") if isinstance(started, dict) else None
    if not job_run_uid:
        raise RuntimeError("The platform did not report a JobRun for the started Job.")
    return str(uuid.UUID(str(job_run_uid)))


def start_job_run(
    job: Any, command_args: list[str], *, sleep: Callable[[float], None] = time.sleep
) -> str:
    """Start one run of `job` with `command_args` and return its JobRun UID.

    A transport failure or a server error leaves the start's outcome unknown: the platform may
    have created the run before the answer was lost. The run is then looked for (same Job, same
    arguments, started since the request) and returned when found; `JobStartUnconfirmed` is
    raised only when none appears, so the caller can say the start is unconfirmed, not failed.
    """
    from mainsequence.client.exceptions import ServerError, TransportError

    requested_at = dt.datetime.now(dt.timezone.utc)
    try:
        started = job.run_job(timeout=JOB_START_TIMEOUT_SECONDS, command_args=command_args)
    except (TransportError, ServerError) as exc:
        job_run_uid = _created_job_run(job, command_args, since=requested_at, sleep=sleep)
        if job_run_uid is None:
            raise JobStartUnconfirmed(
                "The platform did not confirm that the Job started; it may still start. "
                "Check again in a few minutes before starting it again."
            ) from exc
        logger.warning(
            "The start of %s answered %s, but it created the run %s.",
            job.name,
            type(exc).__name__,
            job_run_uid,
        )
        return job_run_uid
    return started_job_run_uid(started)


def _created_job_run(
    job: Any, command_args: list[str], *, since: dt.datetime, sleep: Callable[[float], None]
) -> str | None:
    """The run of `job` a start at `since` created, when the platform lists one."""
    from mainsequence.client import JobRun

    earliest = since - JOB_START_CLOCK_SKEW
    for attempt in range(JOB_START_LOOKUPS):
        if attempt:
            sleep(JOB_START_LOOKUP_INTERVAL_SECONDS)
        try:
            runs = itertools.islice(
                JobRun.iter_filter(job__uid=str(job.uid), timeout=30), JOB_START_LOOKUP_RUNS
            )
            for run in runs:
                if list(run.command_args or []) != list(command_args):
                    continue
                if run.execution_start is None:
                    if run.status is None or run.status in PENDING_JOB_RUN_STATUSES:
                        return str(uuid.UUID(str(run.uid)))
                elif run.execution_start >= earliest:
                    return str(uuid.UUID(str(run.uid)))
        except Exception as exc:  # the platform's own errors carry request internals
            logger.warning("Looking for the run of %s failed (%s).", job.name, type(exc).__name__)
    return None


def start_take_research(
    take_uid: uuid.UUID | str,
    *,
    research_mode: str | None = None,
    created_by: str | None = None,
    execution: str | None = None,
) -> StartedBuild:
    """Research the take's thesis against the universe and store the result (no portfolio)."""
    mode = execution or build_execution()
    uid = str(uuid.UUID(str(take_uid)))
    if mode == "inline":
        from hunch.research.runs import run_take_research

        result = run_take_research(uid, mode=research_mode, created_by=created_by)
        return StartedBuild(execution="inline", take_uid=uid, result=result)
    job = platform_job(TAKE_RESEARCH_JOB_NAME, TAKE_RESEARCH_JOB_PATH)
    args = ["--take-uid", uid]
    if research_mode:
        args += ["--research-mode", research_mode]
    return StartedBuild(execution="job", take_uid=uid, job_run_uid=start_job_run(job, args))


def start_take_build(
    take_uid: uuid.UUID | str,
    *,
    research_uid: uuid.UUID | str | None = None,
    created_by: str | None = None,
    execution: str | None = None,
) -> StartedBuild:
    """Construct the basket from a stored research (the latest by default) and build the
    portfolio.

    The research is resolved here, before anything starts: a take without research answers at
    once instead of starting a Job that fails, and a hosted build pins the research it was
    started for, so a research that completes meanwhile does not change the basket.
    """
    from hunch.research.runs import research_for_build

    mode = execution or build_execution()
    uid = str(uuid.UUID(str(take_uid)))
    research = str(research_for_build(uid, research_uid).uid)
    if mode == "inline":
        from hunch.portfolios.build import build_take

        result = build_take(uid, research_uid=research, created_by=created_by)
        return StartedBuild(execution="inline", take_uid=uid, result=result)
    job = platform_job(TAKE_BUILD_JOB_NAME, TAKE_BUILD_JOB_PATH)
    job_run_uid = start_job_run(job, ["--take-uid", uid, "--research-uid", research])
    return StartedBuild(execution="job", take_uid=uid, job_run_uid=job_run_uid)


def start_portfolio_refresh(
    take_uid: uuid.UUID | str, *, execution: str | None = None
) -> StartedBuild:
    mode = execution or build_execution()
    uid = str(uuid.UUID(str(take_uid)))
    if mode == "inline":
        from hunch.portfolios.build import refresh_take_portfolio

        result = refresh_take_portfolio(uid)
        return StartedBuild(execution="inline", take_uid=uid, result=result)
    job = platform_job(PORTFOLIO_REFRESH_JOB_NAME, PORTFOLIO_REFRESH_JOB_PATH)
    job_run_uid = start_job_run(job, ["--take-uid", uid])
    return StartedBuild(execution="job", take_uid=uid, job_run_uid=job_run_uid)


def job_run_status(job_run_uid: str) -> dict[str, Any] | None:
    """A sanitized view of one JobRun: status, timestamps, and a short failure summary."""
    from mainsequence.client import JobRun

    runs = JobRun.filter(uid=job_run_uid)
    if not runs:
        return None
    run = runs[0]
    return {
        "uid": str(run.uid),
        "status": getattr(run, "status", None),
        "created_at": getattr(run, "created_at", None),
        "started_at": getattr(run, "started_at", None),
        "finished_at": getattr(run, "finished_at", None),
        "command_args": list(getattr(run, "command_args", []) or []),
        "failure_summary": (str(getattr(run, "error_message", "") or "")[:500] or None),
    }


__all__ = [
    "JOB_START_TIMEOUT_SECONDS",
    "PENDING_JOB_RUN_STATUSES",
    "PORTFOLIO_REFRESH_JOB_NAME",
    "PORTFOLIO_REFRESH_JOB_PATH",
    "TAKE_BUILD_JOB_NAME",
    "TAKE_BUILD_JOB_PATH",
    "TAKE_RESEARCH_JOB_NAME",
    "TAKE_RESEARCH_JOB_PATH",
    "JobStartUnconfirmed",
    "StartedBuild",
    "job_run_status",
    "platform_job",
    "start_job_run",
    "start_portfolio_refresh",
    "start_take_build",
    "start_take_research",
    "started_job_run_uid",
]
