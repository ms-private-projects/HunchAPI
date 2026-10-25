"""Starting a take build: inline in this process, or as the workflow-declared platform Job.

Hosted, the API never builds in its own process: it starts the `Hunch Take Build` Job with the
take UID and returns the JobRun to poll. Locally there is no Job, so the build runs inline. The
mode is `HUNCH_BUILD_EXECUTION` (inline by default); nothing else differs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from hunch.settings import build_execution

TAKE_BUILD_JOB_NAME = "Hunch Take Build"
TAKE_BUILD_JOB_PATH = "src/jobs/run_hunch_take_build.py"
PORTFOLIO_REFRESH_JOB_NAME = "Hunch Portfolio Refresh"
PORTFOLIO_REFRESH_JOB_PATH = "src/jobs/run_hunch_portfolio_refresh.py"


@dataclass(slots=True)
class StartedBuild:
    execution: str
    take_uid: str
    job_run_uid: str | None = None
    result: Any | None = None


def _platform_job(name: str, execution_path: str) -> Any:
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


def start_take_build(
    take_uid: uuid.UUID | str,
    *,
    research_mode: str | None = None,
    created_by: str | None = None,
    execution: str | None = None,
) -> StartedBuild:
    mode = execution or build_execution()
    uid = str(uuid.UUID(str(take_uid)))
    if mode == "inline":
        from hunch.portfolios.build import build_take

        result = build_take(uid, research_mode=research_mode, created_by=created_by)
        return StartedBuild(execution="inline", take_uid=uid, result=result)
    job = _platform_job(TAKE_BUILD_JOB_NAME, TAKE_BUILD_JOB_PATH)
    args = ["--take-uid", uid]
    if research_mode:
        args += ["--research-mode", research_mode]
    run = job.run_job(timeout=60, command_args=args)
    return StartedBuild(execution="job", take_uid=uid, job_run_uid=str(getattr(run, "uid", run)))


def start_portfolio_refresh(
    take_uid: uuid.UUID | str, *, execution: str | None = None
) -> StartedBuild:
    mode = execution or build_execution()
    uid = str(uuid.UUID(str(take_uid)))
    if mode == "inline":
        from hunch.portfolios.build import refresh_take_portfolio

        result = refresh_take_portfolio(uid)
        return StartedBuild(execution="inline", take_uid=uid, result=result)
    job = _platform_job(PORTFOLIO_REFRESH_JOB_NAME, PORTFOLIO_REFRESH_JOB_PATH)
    run = job.run_job(timeout=60, command_args=["--take-uid", uid])
    return StartedBuild(execution="job", take_uid=uid, job_run_uid=str(getattr(run, "uid", run)))


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
    "StartedBuild",
    "job_run_status",
    "start_portfolio_refresh",
    "start_take_build",
]
