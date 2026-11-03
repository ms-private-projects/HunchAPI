"""The thesis critique: the deterministic reading, the analysis model's answer and its surfaces."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import anyio
import pytest
from fastapi.testclient import TestClient
from tests.fakes import install_fake_rows
from tests.test_model_roles import FakeInference

from hunch.analysis import critique_thesis, heuristic_critique, inference_critique
from hunch.api.app.identity import ActingUser
from hunch.api.app.main import create_app
from hunch.api.app.mcp_server import build_mcp_server
from hunch.profiles import HunchUserProfile
from hunch.research.models import ResearchError
from hunch.takes import Take
from hunch.takes.services import TakeConstraints

ALICE = "11111111-1111-4111-8111-111111111111"
THESIS = (
    "Humanoid robots are coming to every home within the decade. "
    "Chip supply could be the chokepoint, so I want to hedge the chip makers."
)


def take(thesis: str = THESIS, *, title: str = "Robots at home", **constraints) -> Take:
    return Take(
        uid=uuid.uuid4(),
        owner_user_uid=ALICE,
        title=title,
        thesis_text=thesis,
        constraints_json=TakeConstraints(**constraints).model_dump(),
    )


def test_heuristic_critique_reads_the_structure_and_the_constraints() -> None:
    critique = heuristic_critique(
        take(exclusions=["robotics"], risk_level="high", cash_buffer=0.25, max_positions=4)
    )
    assert critique.mode == "heuristic" and critique.clarity == "clear"
    assert [claim.strength for claim in critique.claims] == ["moderate", "weak"]
    assert critique.claims[1].note.startswith("Hedged")
    assert "robotics" in critique.summary and "12-month" in critique.summary
    assert critique.counterarguments == [] and critique.provider is None
    assert any("decade" in note for note in critique.constraint_notes)
    assert any("hedging or shorting" in note for note in critique.constraint_notes)
    assert any("opposite directions" in note for note in critique.constraint_notes)
    assert any("'robotics'" in note for note in critique.constraint_notes)
    assert any("4 positions" in risk for risk in critique.risks)
    assert critique.suggested_conditions and "stalls" in critique.suggested_conditions[0]
    assert "What would convince you that you are wrong?" in critique.questions
    assert "Over what period do you expect this to play out?" not in critique.questions


def test_heuristic_critique_of_a_vague_thesis_asks_the_missing_questions() -> None:
    critique = heuristic_critique(
        take("Something will happen.", title="Vague", change_my_mind="- Nothing happens")
    )
    assert critique.clarity == "vague"
    assert critique.suggested_conditions == []
    assert critique.questions == [
        "Over what period do you expect this to play out?",
        "Who loses if you are right?",
        "Which industries or companies benefit first, and which only later?",
    ]


def _answer(**changes) -> dict:
    answer = {
        "summary": "Robots at home within ten years, with chips as the chokepoint.",
        "clarity": "partly_clear",
        "claims": [
            {"claim": "Humanoid robots reach homes", "strength": "weak", "note": "Early."},
            {"claim": "Chips are the chokepoint", "strength": "moderate", "note": "Plausible."},
        ],
        "assumptions": ["Consumers pay for home robots."],
        "counterarguments": ["Industrial use comes first."],
        "risks": [f"Risk {index}" for index in range(12)],
        "suggested_conditions": ["No home robot ships at scale by 2029."],
        "constraint_notes": ["A decade thesis on a 12-month horizon."],
        "questions": ["Which tasks first?"],
    }
    answer.update(changes)
    return answer


def test_inference_critique_runs_on_the_analysis_role_and_bounds_the_answer(monkeypatch) -> None:
    monkeypatch.setenv("HUNCH_INFERENCE_PROVIDER", "meta")
    monkeypatch.setenv("HUNCH_INFERENCE_MODEL", "muse-spark-1.3")
    monkeypatch.setenv("HUNCH_MODEL_ANALYSIS", "model=muse-spark-1.2")
    client = FakeInference(_answer(summary="x" * 5000))
    critique = inference_critique(take(), client=client)
    (call,) = client.calls
    assert call["metadata"]["model_role"] == "analysis"
    assert call["metadata"]["operation"] == "hunch-thesis-critique"
    assert call["model"] == "muse-spark-1.2"
    assert call["response_schema"]["required"][0] == "summary"
    assert "Chip supply" in call["messages"][1]["content"]
    assert "robotics" in call["messages"][1]["content"]
    assert critique.mode == "inference"
    assert critique.clarity == "partly_clear"
    assert [claim.strength for claim in critique.claims] == ["weak", "moderate"]
    assert len(critique.risks) == 8 and len(critique.summary) == 2000
    assert critique.model == "muse-spark-1.2" and critique.provider == "meta"
    assert critique.inference_request_uids == ["req-1"]


def test_inference_critique_rejects_an_answer_off_the_contract() -> None:
    bad = FakeInference(_answer(claims=[{"claim": "x", "strength": "certain", "note": ""}]))
    with pytest.raises(ResearchError, match="contract"):
        inference_critique(take(), client=bad)
    with pytest.raises(ResearchError, match="contract"):
        inference_critique(take(), client=FakeInference(_answer(clarity="crystal")))


def test_critique_thesis_follows_the_configured_mode(monkeypatch) -> None:
    monkeypatch.setenv("HUNCH_RESEARCH_MODE", "heuristic")
    assert critique_thesis(take()).mode == "heuristic"
    assert critique_thesis(take(), mode="inference", client=FakeInference(_answer())).mode == (
        "inference"
    )


@pytest.fixture
def client(local_caller, monkeypatch) -> TestClient:
    install_fake_rows(monkeypatch, HunchUserProfile, Take)
    monkeypatch.setenv("HUNCH_RESEARCH_MODE", "heuristic")
    return TestClient(create_app(), headers=local_caller.headers)


def test_critique_route_answers_the_owner_and_readers_of_published_takes(
    client, local_caller
) -> None:
    created = client.post("/v1/takes", json={"title": "Robots", "thesis_text": THESIS})
    uid = created.json()["uid"]
    response = client.post(f"/v1/takes/{uid}/actions/critique-thesis")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["take_uid"] == uid and body["mode"] == "heuristic"
    assert body["claims"][1]["strength"] == "weak"
    assert body["disclaimers"]
    assert client.get(f"/v1/takes/{uid}").json()["thesis_text"] == THESIS

    other = TestClient(create_app(), headers=local_caller.other_headers)
    assert other.post(f"/v1/takes/{uid}/actions/critique-thesis").status_code == 404
    Take.update(uid, status="built")
    assert client.post(f"/v1/takes/{uid}/actions/publish").status_code == 200
    public = other.post(
        f"/v1/takes/{uid}/actions/critique-thesis", json={"research_mode": "heuristic"}
    )
    assert public.status_code == 200 and public.json()["mode"] == "heuristic"
    assert client.post(f"/v1/takes/{uid}/actions/critique-thesis", json={"x": 1}).status_code == (
        422
    )


def test_critique_route_reports_a_failed_model_call_without_the_thesis(client) -> None:
    created = client.post("/v1/takes", json={"title": "Robots", "thesis_text": "zebra-probe"})
    uid = created.json()["uid"]
    with patch(
        "hunch.api.app.services.analysis.critique_thesis",
        side_effect=ResearchError("The analysis model call failed (TimeoutError)."),
    ):
        response = client.post(f"/v1/takes/{uid}/actions/critique-thesis")
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "research_unavailable"
    assert "zebra-probe" not in response.text


def test_analyze_tool_is_read_only_and_critiques_through_the_service(monkeypatch) -> None:
    monkeypatch.setenv("HUNCH_RESEARCH_MODE", "heuristic")
    row = take()
    with (
        patch("hunch.api.app.identity.acting_user", return_value=ActingUser(ALICE, None)),
        patch.object(Take, "get_by_uid", side_effect=lambda uid: row if uid == row.uid else None),
    ):
        server = build_mcp_server()
        tools = {tool.name: tool for tool in anyio.run(server.list_tools)}
        tool = tools["hunch_analyze_take"]
        assert tool.annotations.read_only_hint
        assert tool.meta == {"mainsequence.ai/timeout-seconds/v1": 120}
        result = anyio.run(
            server.call_tool,
            "hunch_analyze_take",
            {"operation": "critique_thesis", "take_uid": str(row.uid)},
        )
        assert not result.is_error, result.content[0].text
        missing = anyio.run(
            server.call_tool,
            "hunch_analyze_take",
            {"operation": "critique_thesis", "take_uid": str(uuid.uuid4())},
        )
        assert missing.is_error
