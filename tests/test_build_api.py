"""Research, build, activate, revisions, weights and performance routes, with the pipeline
stubbed. Research and construction are independent steps (ADR 0008)."""

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
from hunch.research.models import CandidateInstrument, ResearchBrief, ResearchOutput
from hunch.takes import Take
from hunch.takes.research import TakeResearch
from hunch.takes.revisions import TakeRevision

THESIS = "Humanoid robots are coming to every home within the decade."
NOW = dt.datetime(2026, 10, 25, 9, 0, tzinfo=dt.timezone.utc)
JOB_RUN_UID = "1a50150c-3316-4d73-8b3b-fe151f21461f"


@pytest.fixture
def client(local_caller, monkeypatch) -> TestClient:
    install_fake_rows(monkeypatch, HunchUserProfile, Take, TakeResearch, TakeRevision)
    return TestClient(create_app(), headers=local_caller.headers)


def _fake_research(take_uid, *, mode=None, now=None, created_by=None):
    """The research step without a universe: one stored heuristic research."""
    take = Take.get_by_uid(take_uid)
    output = ResearchOutput(
        mode="heuristic",
        brief=ResearchBrief(claims=[take.title], keywords=["robots"]),
        candidates=[CandidateInstrument(ticker="TSLA", role="pure_play", conviction=0.9)],
        rationale_md="## Robots\n\nBecause.",
    )
    row = TakeResearch.create(
        take_uid=take.uid,
        number=len(TakeResearch.filter(take_uid=take.uid)) + 1,
        mode=output.mode,
        brief_json=output.brief.model_dump(),
        candidates_json=[c.model_dump() for c in output.candidates],
        rationale_md=output.rationale_md,
        evidence_json=[],
        created_by=created_by or "job",
        created_at=NOW,
    )
    return SimpleNamespace(take=take, research=row, output=output)


def _fake_build(take_uid, *, research_uid=None, created_by=None):
    take = Take.update(take_uid, status="built", signal_uid="sig-1", updated_at=NOW)
    revision = TakeRevision.create(
        take_uid=take.uid,
        revision=1,
        research_uid=uuid.UUID(str(research_uid)) if research_uid else None,
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
        created_by=created_by or "job",
        signal_time_index=NOW,
        created_at=NOW,
    )
    return SimpleNamespace(take=take, revision=revision)


def test_research_inline_is_kept_by_the_take_and_read_back(client, local_caller, monkeypatch):
    created = client.post("/v1/takes", json={"title": "Robots", "thesis_text": THESIS}).json()
    uid = created["uid"]
    monkeypatch.setenv("HUNCH_BUILD_EXECUTION", "inline")
    with patch("hunch.research.runs.run_take_research", side_effect=_fake_research):
        first = client.post(
            f"/v1/takes/{uid}/actions/research", json={"research_mode": "heuristic"}
        )
        second = client.post(f"/v1/takes/{uid}/actions/research")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["execution"] == "inline" and body["job_run_uid"] is None
    assert body["research"]["number"] == 1 and body["research"]["mode"] == "heuristic"
    assert body["research"]["candidates"][0]["ticker"] == "TSLA"
    assert "weight" not in body["research"]["candidates"][0]
    assert body["research"]["created_by"] == "user"
    assert second.json()["research"]["number"] == 2

    listed = client.get(f"/v1/takes/{uid}/research")
    assert listed.status_code == 200 and [r["number"] for r in listed.json()] == [2, 1]
    one = client.get(f"/v1/takes/{uid}/research/{body['research']['uid']}")
    assert one.status_code == 200 and one.json()["uid"] == body["research"]["uid"]
    assert client.get(f"/v1/takes/{uid}/research/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/v1/takes/{uid}/research/not-a-uid").status_code == 404

    other = TestClient(create_app(), headers=local_caller.other_headers)
    assert other.post(f"/v1/takes/{uid}/actions/research").status_code == 404
    assert other.get(f"/v1/takes/{uid}/research").status_code == 404


def test_a_take_without_research_cannot_be_built(client, monkeypatch) -> None:
    created = client.post("/v1/takes", json={"title": "Robots", "thesis_text": THESIS}).json()
    monkeypatch.setenv("HUNCH_BUILD_EXECUTION", "inline")
    built = client.post(f"/v1/takes/{created['uid']}/actions/build")
    assert built.status_code == 409, built.text
    assert "Research the take" in built.json()["detail"]["message"]


def test_build_inline_constructs_from_the_research_and_activation_follows(
    client, monkeypatch
) -> None:
    created = client.post("/v1/takes", json={"title": "Robots", "thesis_text": THESIS}).json()
    uid = created["uid"]
    monkeypatch.setenv("HUNCH_BUILD_EXECUTION", "inline")
    with patch("hunch.research.runs.run_take_research", side_effect=_fake_research):
        research = client.post(f"/v1/takes/{uid}/actions/research").json()["research"]
    with patch("hunch.portfolios.build.build_take", side_effect=_fake_build):
        built = client.post(
            f"/v1/takes/{uid}/actions/build", json={"research_uid": research["uid"]}
        )
    assert built.status_code == 200, built.text
    body = built.json()
    assert body["execution"] == "inline" and body["take"]["status"] == "built"
    assert body["revision"]["weights"][0]["ticker"] == "TSLA"
    assert body["revision"]["research_uid"] == research["uid"]
    assert body["revision"]["created_by"] == "user"

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


def _platform_jobs() -> tuple[dict[str, SimpleNamespace], list[tuple[str, list[str]]]]:
    """The research and build Jobs of the branch, recording the runs they are asked for."""
    started: list[tuple[str, list[str]]] = []
    jobs = {}
    for name, path in (
        (builds.TAKE_RESEARCH_JOB_NAME, builds.TAKE_RESEARCH_JOB_PATH),
        (builds.TAKE_BUILD_JOB_NAME, builds.TAKE_BUILD_JOB_PATH),
    ):
        job = SimpleNamespace(name=name, execution_path=path)

        def run_job(timeout, command_args, name=name):
            started.append((name, command_args))
            # Job.run_job answers the platform's run-job body, not a JobRun.
            return {"message": f"Job '{name}' has started.", "job_run_uid": JOB_RUN_UID}

        job.run_job = run_job
        jobs[name] = job
    return jobs, started


def test_research_and_build_as_jobs_return_the_job_run(client, monkeypatch) -> None:
    created = client.post("/v1/takes", json={"title": "Robots", "thesis_text": THESIS}).json()
    uid = created["uid"]
    research_uid = str(uuid.uuid4())
    monkeypatch.setenv("HUNCH_BUILD_EXECUTION", "job")
    jobs, started = _platform_jobs()
    with patch("mainsequence.client.Job") as job_model:
        job_model.filter.side_effect = lambda name, timeout: [jobs[name]]
        researched = client.post(
            f"/v1/takes/{uid}/actions/research", json={"research_mode": "heuristic"}
        )
        built = client.post(f"/v1/takes/{uid}/actions/build")
        rebuilt = client.post(f"/v1/takes/{uid}/actions/build", json={"research_uid": research_uid})
    assert researched.status_code == 200, researched.text
    assert researched.json() == {
        "execution": "job",
        "take": researched.json()["take"],
        "research": None,
        "job_run_uid": JOB_RUN_UID,
    }
    assert built.status_code == 200, built.text
    assert built.json() == {
        "execution": "job",
        "take": built.json()["take"],
        "revision": None,
        "job_run_uid": JOB_RUN_UID,
    }
    assert rebuilt.status_code == 200, rebuilt.text
    assert started == [
        (builds.TAKE_RESEARCH_JOB_NAME, ["--take-uid", uid, "--research-mode", "heuristic"]),
        (builds.TAKE_BUILD_JOB_NAME, ["--take-uid", uid]),
        (builds.TAKE_BUILD_JOB_NAME, ["--take-uid", uid, "--research-uid", research_uid]),
    ]


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
    assert other.post(f"/v1/takes/{created['uid']}/actions/research").status_code == 404
    assert other.post(f"/v1/takes/{created['uid']}/actions/build").status_code == 404
    assert other.get(f"/v1/takes/{created['uid']}/revisions").status_code == 404
    assert other.get(f"/v1/takes/{created['uid']}/research").status_code == 404
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
