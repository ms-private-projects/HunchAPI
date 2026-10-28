"""Build, activate, revisions, weights and performance routes, with the pipeline stubbed."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from tests.fakes import install_fake_rows

from hunch.api.app.main import create_app
from hunch.operations import builds
from hunch.profiles import HunchUserProfile
from hunch.takes import Take
from hunch.takes.revisions import TakeRevision

THESIS = "Humanoid robots are coming to every home within the decade."
NOW = dt.datetime(2026, 10, 25, 9, 0, tzinfo=dt.timezone.utc)
JOB_RUN_UID = "1a50150c-3316-4d73-8b3b-fe151f21461f"


@pytest.fixture
def client(local_caller, monkeypatch) -> TestClient:
    install_fake_rows(monkeypatch, HunchUserProfile, Take, TakeRevision)
    return TestClient(create_app(), headers=local_caller.headers)


def _fake_build(take_uid, *, research_mode=None, created_by=None):
    take = Take.update(take_uid, status="built", signal_uid="sig-1", updated_at=NOW)
    revision = TakeRevision.create(
        take_uid=take.uid,
        revision=1,
        kind="initial",
        rationale_md="## Robots\n\nBecause.",
        weights_json=[
            {
                "figi": "BBG000N9MNX3",
                "ticker": "TSLA",
                "name": "Tesla",
                "weight": 0.5,
                "role": "pure_play",
                "reason": "x",
            }
        ],
        research_json={"cash_weight": 0.5, "guardrail_notes": ["1 positions"], "candidates": []},
        created_by=research_mode or "inference",
        signal_time_index=NOW,
        created_at=NOW,
    )
    return SimpleNamespace(take=take, revision=revision)


def test_build_inline_returns_the_revision_and_activation_follows(client, monkeypatch) -> None:
    created = client.post("/v1/takes", json={"title": "Robots", "thesis_text": THESIS}).json()
    uid = created["uid"]
    monkeypatch.setenv("HUNCH_BUILD_EXECUTION", "inline")
    with patch("hunch.portfolios.build.build_take", side_effect=_fake_build):
        built = client.post(f"/v1/takes/{uid}/actions/build", json={"research_mode": "heuristic"})
    assert built.status_code == 200, built.text
    body = built.json()
    assert body["execution"] == "inline" and body["take"]["status"] == "built"
    assert body["revision"]["weights"][0]["ticker"] == "TSLA"
    assert body["revision"]["created_by"] == "heuristic"

    with patch("hunch.portfolios.build.HunchPortfolio") as portfolio_rows:
        portfolio_rows.filter.return_value = []
        activated = client.post(f"/v1/takes/{uid}/actions/activate-practice")
    assert activated.status_code == 200 and activated.json()["status"] == "active_practice"

    revisions = client.get(f"/v1/takes/{uid}/revisions")
    assert revisions.status_code == 200 and revisions.json()[0]["revision"] == 1

    with patch(
        "hunch.api.app.services.portfolios.take_weights",
        return_value=[
            {
                "figi": "BBG000N9MNX3",
                "ticker": "TSLA",
                "name": "Tesla",
                "weight": 0.5,
                "price": None,
                "time_index": NOW,
            }
        ],
    ):
        weights = client.get(f"/v1/takes/{uid}/weights")
    assert weights.status_code == 200
    assert weights.json()["invested"] == 0.5 and weights.json()["cash"] == 0.5

    with patch(
        "hunch.api.app.services.portfolios.take_performance",
        return_value=[
            {"time_index": NOW, "close": 1.0, "return": 0.0},
            {"time_index": NOW + dt.timedelta(days=1), "close": 1.01, "return": 0.01},
        ],
    ):
        performance = client.get(f"/v1/takes/{uid}/performance")
    assert performance.status_code == 200
    frame = performance.json()
    assert frame["status"] == "ready" and frame["columns"] == ["time_index", "close", "return"]
    assert len(frame["rows"]) == 2 and frame["source"]["context"]["simulated"] is True


def test_build_as_a_job_returns_the_job_run(client, monkeypatch) -> None:
    created = client.post("/v1/takes", json={"title": "Robots", "thesis_text": THESIS}).json()
    monkeypatch.setenv("HUNCH_BUILD_EXECUTION", "job")
    job = SimpleNamespace(
        name=builds.TAKE_BUILD_JOB_NAME, execution_path=builds.TAKE_BUILD_JOB_PATH
    )
    started: list[list[str]] = []

    def run_job(timeout, command_args):
        started.append(command_args)
        # Job.run_job answers the platform's run-job body, not a JobRun.
        return {"message": "Job 'Hunch Take Build' has started.", "job_run_uid": JOB_RUN_UID}

    job.run_job = run_job
    with patch("mainsequence.client.Job") as job_model:
        job_model.filter.return_value = [job]
        built = client.post(f"/v1/takes/{created['uid']}/actions/build")
    assert built.status_code == 200, built.text
    assert built.json() == {
        "execution": "job",
        "take": built.json()["take"],
        "revision": None,
        "job_run_uid": JOB_RUN_UID,
    }
    assert started == [["--take-uid", created["uid"]]]


def test_a_started_job_without_a_job_run_fails_the_build(client, monkeypatch) -> None:
    created = client.post("/v1/takes", json={"title": "Robots", "thesis_text": THESIS}).json()
    monkeypatch.setenv("HUNCH_BUILD_EXECUTION", "job")
    job = SimpleNamespace(
        name=builds.TAKE_BUILD_JOB_NAME, execution_path=builds.TAKE_BUILD_JOB_PATH
    )
    job.run_job = lambda timeout, command_args: {"message": "queued"}
    with patch("mainsequence.client.Job") as job_model:
        job_model.filter.return_value = [job]
        built = client.post(f"/v1/takes/{created['uid']}/actions/build")
    assert built.status_code >= 500
    assert JOB_RUN_UID not in built.text


def test_only_owners_build_and_others_read_published_portfolios(client, local_caller) -> None:
    created = client.post("/v1/takes", json={"title": "Robots", "thesis_text": THESIS}).json()
    other = TestClient(create_app(), headers=local_caller.other_headers)
    assert other.post(f"/v1/takes/{created['uid']}/actions/build").status_code == 404
    assert other.get(f"/v1/takes/{created['uid']}/revisions").status_code == 404
    assert client.post(f"/v1/takes/{uuid.uuid4()}/actions/activate-practice").status_code == 404


def test_instruments_routes_serve_the_universe(client) -> None:
    rows = [
        SimpleNamespace(
            figi=f"BBG00000000{i}",
            ticker=t,
            name=n,
            exchange_code="US",
            security_type="Common Stock",
            sector=s,
            themes=th,
            is_etf=False,
            is_leveraged=False,
            is_inverse=False,
            is_tradable=True,
        )
        for i, (t, n, s, th) in enumerate(
            [
                ("NVDA", "NVIDIA", "Information Technology", ["ai"]),
                ("KO", "Coca-Cola", "Consumer Staples", ["beverages"]),
            ]
        )
    ]
    with patch("hunch.api.app.services.instruments.list_instruments", return_value=rows):
        listed = client.get("/v1/instruments", params={"search": "ai"})
        one = client.get("/v1/instruments/ko")
        missing = client.get("/v1/instruments/ZZZZ")
        discovery = client.get("/v1/instruments/discovery")
    assert listed.status_code == 200 and listed.json()["pageInfo"]["totalItems"] == 1
    assert one.status_code == 200 and one.json()["ticker"] == "KO"
    assert missing.status_code == 404
    assert discovery.json()["resource"]["id"] == "instruments"
