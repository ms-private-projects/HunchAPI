"""Research on recorded inference asks for every field, and an answer that leaves the brief's
claims or a candidate's case empty is retried once, then refused."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from tests.test_research import take, universe

from hunch.research.inference import SYSTEM_PROMPT, inference_research, response_schema
from hunch.research.models import ResearchError

THESIS = "Humanoid robots move from factories into homes within five years."


def _candidate(ticker: str, role: str, case: str) -> dict:
    return {
        "ticker": ticker,
        "role": role,
        "case": case,
        "risks": ["Adoption is slower than expected."],
        "conviction": 0.7,
        "citations": [],
    }


COMPLETE = {
    "brief": {
        "claims": ["Household humanoid robots ship in volume by 2030.", "  "],
        "beneficiaries": ["robot makers"],
        "losers": [],
        "keywords": ["humanoid"],
    },
    "candidates": [
        _candidate("TSLA", "pure_play", "Optimus is Tesla's humanoid programme."),
        _candidate("NVDA", "supplier", "Its Jetson modules and simulation stack train robots."),
        _candidate("ROK", "enabler", "Factory automation spreads the same motion control."),
    ],
    "rationale_md": "Robots at home.",
}

# The answer Muse Wonder gave on development on 2026-11-02: schema-valid, but empty.
INCOMPLETE = {
    "brief": {"claims": [], "beneficiaries": [], "losers": [], "keywords": ["humanoid"]},
    "candidates": [
        _candidate("TSLA", "pure_play", ""),
        _candidate("NVDA", "supplier", "   "),
        _candidate("ROK", "enabler", "Factory automation spreads the same motion control."),
    ],
    "rationale_md": "Robots at home.",
}


class ScriptedInference:
    """Answers each recorded completion with the next scripted content."""

    def __init__(self, *answers: dict) -> None:
        self.answers = list(answers)
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        number = len(self.calls)
        return SimpleNamespace(
            status="completed",
            content_available=True,
            output={"content": self.answers[number - 1]},
            request_uid=f"req-{number}",
            conversation_uid=f"conv-{number}",
            provider=kwargs["provider"],
            model=kwargs["model"],
        )


@pytest.fixture(autouse=True)
def research_on_wonder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUNCH_MODEL_RESEARCH", "provider=meta model=muse-wonder-1.0")


def test_the_schema_requires_claims_and_every_case() -> None:
    schema = response_schema(["TSLA"])
    claims = schema["properties"]["brief"]["properties"]["claims"]
    assert claims["minItems"] == 1 and claims["items"]["minLength"] == 1
    case = schema["properties"]["candidates"]["items"]["properties"]["case"]
    assert case["minLength"] == 1


def test_the_prompt_describes_every_field_and_role() -> None:
    schema = response_schema(["TSLA"])
    brief = schema["properties"]["brief"]["properties"]
    candidate = schema["properties"]["candidates"]["items"]["properties"]
    for name in brief:
        assert f"`brief.{name}`" in SYSTEM_PROMPT
    for name in candidate:
        assert f"`candidates[].{name}`" in SYSTEM_PROMPT
    assert "`rationale_md`" in SYSTEM_PROMPT
    for role in candidate["role"]["enum"]:
        assert f"- `{role}`:" in SYSTEM_PROMPT
    assert "When the universe holds no pure play" in SYSTEM_PROMPT


def test_a_complete_answer_is_kept_from_one_call() -> None:
    client = ScriptedInference(COMPLETE)
    output = inference_research(take(THESIS), universe(), number=3, client=client)
    (call,) = client.calls
    assert call["metadata"]["attempt"] == 1 and call["metadata"]["research_number"] == 3
    assert output.brief.claims == ["Household humanoid robots ship in volume by 2030."]
    assert all(candidate.case for candidate in output.candidates)
    assert output.inference_request_uids == ["req-1"]


def test_an_answer_with_empty_fields_is_retried_once_with_a_note() -> None:
    client = ScriptedInference(INCOMPLETE, COMPLETE)
    subject = take(THESIS)
    output = inference_research(subject, universe(), number=2, client=client)
    first, retry = client.calls
    assert "incomplete" not in first["messages"][1]["content"]
    note = retry["messages"][1]["content"].removeprefix(first["messages"][1]["content"])
    assert "brief.claims" in note
    assert "the case of TSLA" in note and "the case of NVDA" in note
    assert "the case of ROK" not in note
    assert retry["metadata"]["attempt"] == 2
    assert retry["idempotency_key"].startswith(f"hunch-take-{subject.uid}-research-2-retry-")
    assert output.brief.claims == ["Household humanoid robots ship in volume by 2030."]
    assert [candidate.ticker for candidate in output.candidates] == ["TSLA", "NVDA", "ROK"]
    assert all(candidate.case for candidate in output.candidates)
    assert output.inference_request_uids == ["req-1", "req-2"]
    assert output.conversation_uid == "conv-2"
    assert (output.provider, output.model) == ("meta", "muse-wonder-1.0")


def test_a_second_incomplete_answer_is_refused() -> None:
    client = ScriptedInference(INCOMPLETE, INCOMPLETE, COMPLETE)
    with pytest.raises(ResearchError, match="empty twice"):
        inference_research(take(THESIS), universe(), client=client)
    assert len(client.calls) == 2


def test_an_answer_off_the_contract_is_refused_without_a_retry() -> None:
    client = ScriptedInference({"brief": {"claims": ["x"]}, "candidates": [{"ticker": ""}]})
    with pytest.raises(ResearchError, match="does not match the contract"):
        inference_research(take(THESIS), universe(), client=client)
    assert len(client.calls) == 1
