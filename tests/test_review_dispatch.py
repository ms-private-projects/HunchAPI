"""The scheduled review sweep: one Job run per take, in batches, followed to the end."""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from hunch.operations.reviews import (
    START_FAILED_STATUS,
    TIMED_OUT_STATUS,
    DispatchedReview,
    dispatch_reviews,
)
from hunch.settings import review_dispatch

TAKES = [str(uuid.uuid4()) for _ in range(5)]
LAUNCHER = Path(__file__).resolve().parents[1] / "src/jobs/run_hunch_daily_review.py"


def _launcher():
    spec = importlib.util.spec_from_file_location("run_hunch_daily_review", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakePlatform:
    """Starts runs and moves each one to its scripted end after `settle_after` polls."""

    def __init__(self, ends: dict[str, str], *, settle_after: int = 2, refuse: set | None = None):
        self.ends = ends
        self.settle_after = settle_after
        self.refuse = refuse or set()
        self.started: list[list[str]] = [[]]
        self.polls: dict[str, int] = {}
        self.sleeps: list[float] = []
        self.now = 0.0

    def start(self, take_uid, *, research_mode=None):
        if take_uid in self.refuse:
            raise RuntimeError("The platform refused the run.")
        run_uid = f"run-{take_uid[:8]}"
        self.started[-1].append(take_uid)
        return run_uid

    def state(self, run_uid):
        self.polls[run_uid] = self.polls.get(run_uid, 0) + 1
        if self.polls[run_uid] < self.settle_after:
            return "RUNNING", None
        take = next(t for t in TAKES if run_uid == f"run-{t[:8]}")
        end = self.ends.get(take, "SUCCEEDED")
        return end, ("boom" if end != "SUCCEEDED" else None)

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds
        self.started.append([])

    def clock(self):
        return self.now


def test_dispatch_runs_in_batches_and_reports_each_end() -> None:
    platform = FakePlatform({TAKES[3]: "FAILED"}, refuse={TAKES[1]})
    results = dispatch_reviews(
        TAKES,
        batch_size=2,
        poll_seconds=5,
        start=platform.start,
        state=platform.state,
        sleep=platform.sleep,
        clock=platform.clock,
    )
    assert [r.take_uid for r in results] == TAKES
    by_take = {r.take_uid: r for r in results}
    assert by_take[TAKES[0]].succeeded and by_take[TAKES[0]].job_run_uid.startswith("run-")
    assert by_take[TAKES[1]].status == START_FAILED_STATUS
    assert by_take[TAKES[1]].job_run_uid is None
    assert by_take[TAKES[1]].failure_summary == "RuntimeError"
    assert by_take[TAKES[3]].status == "FAILED" and by_take[TAKES[3]].failure_summary == "boom"
    assert by_take[TAKES[4]].succeeded
    # Batches of two: the third run starts only after the first batch ended.
    batches = [batch for batch in platform.started if batch]
    assert batches == [[TAKES[0]], [TAKES[2], TAKES[3]], [TAKES[4]]]
    assert all(seconds == 5 for seconds in platform.sleeps)


def test_dispatch_times_out_a_batch_that_never_ends() -> None:
    platform = FakePlatform({}, settle_after=10_000)
    results = dispatch_reviews(
        TAKES[:2],
        batch_size=2,
        poll_seconds=30,
        batch_timeout_seconds=90,
        start=platform.start,
        state=platform.state,
        sleep=platform.sleep,
        clock=platform.clock,
    )
    assert [r.status for r in results] == [TIMED_OUT_STATUS, TIMED_OUT_STATUS]
    assert all("90 seconds" in r.failure_summary for r in results)
    assert len(platform.sleeps) == 3


def test_dispatch_refuses_an_empty_batch_size() -> None:
    with pytest.raises(ValueError):
        dispatch_reviews(
            TAKES, batch_size=0, start=lambda *a, **k: "x", state=lambda u: ("SUCCEEDED", None)
        )


def test_review_dispatch_setting(monkeypatch) -> None:
    monkeypatch.delenv("HUNCH_REVIEW_DISPATCH", raising=False)
    assert review_dispatch() == "inline"
    monkeypatch.setenv("HUNCH_REVIEW_DISPATCH", "job")
    assert review_dispatch() == "job"
    monkeypatch.setenv("HUNCH_REVIEW_DISPATCH", "sideways")
    with pytest.raises(ValueError):
        review_dispatch()


def _rows():
    return [
        SimpleNamespace(uid=uuid.UUID(TAKES[0]), status="active_practice"),
        SimpleNamespace(uid=uuid.UUID(TAKES[1]), status="draft"),
        SimpleNamespace(uid=uuid.UUID(TAKES[2]), status="active_funded"),
    ]


def test_scheduled_launcher_dispatches_jobs_and_reports(monkeypatch, capsys) -> None:
    launcher = _launcher()
    monkeypatch.setenv("HUNCH_REVIEW_DISPATCH", "job")
    seen = {}

    def fake_dispatch(targets, *, research_mode=None):
        seen["targets"] = list(targets)
        seen["research_mode"] = research_mode
        return [
            DispatchedReview(TAKES[0], "run-a", "SUCCEEDED"),
            DispatchedReview(TAKES[2], "run-c", "FAILED", "boom"),
        ]

    with (
        patch("hunch.migrations.schema_gate.skip_if_schema_behind", return_value=False),
        patch("hunch.runtime.start_markets_engine"),
        patch("hunch.takes.Take.filter", return_value=_rows()),
        patch("hunch.operations.reviews.dispatch_reviews", side_effect=fake_dispatch),
        patch("hunch.operations.reviews.run_review") as run_review,
    ):
        code = launcher.main(["--scheduled", "--research-mode", "inference"])
    assert code == 1
    assert seen == {"targets": [TAKES[0], TAKES[2]], "research_mode": "inference"}
    run_review.assert_not_called()
    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    assert lines[0] == {"take_uid": TAKES[0], "job_run_uid": "run-a", "status": "SUCCEEDED"}
    assert lines[1]["status"] == "FAILED"
    assert lines[-1] == {"dispatched": 2, "failed": 1, "succeeded": 1}


def test_scheduled_launcher_reviews_inline_by_default(monkeypatch, capsys) -> None:
    launcher = _launcher()
    monkeypatch.delenv("HUNCH_REVIEW_DISPATCH", raising=False)
    with (
        patch("hunch.migrations.schema_gate.skip_if_schema_behind", return_value=False),
        patch("hunch.runtime.start_markets_engine"),
        patch("hunch.takes.Take.filter", return_value=_rows()),
        patch("hunch.operations.reviews.dispatch_reviews") as dispatch,
        patch(
            "hunch.operations.reviews.run_review",
            return_value=SimpleNamespace(outcome="hold"),
        ) as run_review,
    ):
        code = launcher.main(["--scheduled"])
    assert code == 0
    dispatch.assert_not_called()
    assert run_review.call_count == 2
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {
        "failed": 0,
        "reviewed": 2,
    }
