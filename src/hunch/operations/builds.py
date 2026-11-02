"""Starting a research, a build or a refresh: inline in this process, or as a platform Job.

Research and construction are independent steps (ADR 0008), each with its own Job: `Hunch Take
Research` studies the target universe and stores a numbered research; `Hunch Take Build`
constructs the basket from a stored research and (re)builds the portfolio. Hosted, the API never
runs either in its own process: it starts the Job with the take UID and returns the JobRun to
poll. Locally there is no Job, so the step runs inline. The mode is `HUNCH_BUILD_EXECUTION`
(inline by default); nothing else differs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from hunch.settings import build_execution

TAKE_RESEARCH_JOB_NAME = "Hunch Take Research"
TAKE_RESEARCH_JOB_PATH = "src/jobs/run_hunch_take_research.py"
TAKE_BUILD_JOB_NAME = "Hunch Take Build"
TAKE_BUILD_JOB_PATH = "src/jobs/run_hunch_take_build.py"
PORTFOLIO_REFRESH_JOB_NAME = "Hunch Portfolio Refresh"
PORTFOLIO_REFRESH_JOB_PATH = "src/jobs/run_hunch_portfolio_refresh.py"


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


def started_job_run_uid(started: Any) -> str:
    """The JobRun UID from `Job.run_job`, which answers `{"message": ..., "job_run_uid": ...}`."""
    job_run_uid = started.get("job_run_uid") if isinstance(started, dict) else None
    if not job_run_uid:
        raise RuntimeError("The platform did not report a JobRun for the started Job.")
    return str(uuid.UUID(str(job_run_uid)))


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
    started = job.run_job(timeout=60, command_args=args)
    return StartedBuild(execution="job", take_uid=uid, job_run_uid=started_job_run_uid(started))


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
    started = job.run_job(timeout=60, command_args=["--take-uid", uid, "--research-uid", research])
    return StartedBuild(execution="job", take_uid=uid, job_run_uid=started_job_run_uid(started))


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
    started = job.run_job(timeout=60, command_args=["--take-uid", uid])
    return StartedBuild(execution="job", take_uid=uid, job_run_uid=started_job_run_uid(started))


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
    "PORTFOLIO_REFRESH_JOB_NAME",
    "PORTFOLIO_REFRESH_JOB_PATH",
    "TAKE_BUILD_JOB_NAME",
    "TAKE_BUILD_JOB_PATH",
    "TAKE_RESEARCH_JOB_NAME",
    "TAKE_RESEARCH_JOB_PATH",
    "StartedBuild",
    "job_run_status",
    "platform_job",
    "start_portfolio_refresh",
    "start_take_build",
    "start_take_research",
    "started_job_run_uid",
]
