"""Research: the heuristic matcher proposes from the universe only and the guardrails decide."""

from __future__ import annotations

import uuid

import pytest

from hunch.instruments import HunchInstrument
from hunch.instruments.services import universe_fixture
from hunch.research import GuardrailError, apply_guardrails, propose_basket
from hunch.research.heuristic import heuristic_research, thesis_themes
from hunch.research.models import CandidateInstrument
from hunch.takes import Take
from hunch.takes.services import TakeConstraints

ALICE = "11111111-1111-4111-8111-111111111111"


def universe() -> list[HunchInstrument]:
    return [
        HunchInstrument(
            figi=item["figi"],
            asset_uid=uuid.uuid4(),
            ticker=item["ticker"],
            name=item["name"],
            exchange_code=item["exchange_code"],
            security_type=item["security_type"],
            sector=item["sector"],
            themes_json=item["themes"],
            is_etf=item["is_etf"],
            is_leveraged=item["is_leveraged"],
            is_inverse=item["is_inverse"],
        )
        for item in universe_fixture()
    ]


def take(thesis: str, *, title: str = "Robots at home", **constraints) -> Take:
    return Take(
        uid=uuid.uuid4(),
        owner_user_uid=ALICE,
        title=title,
        thesis_text=thesis,
        constraints_json=TakeConstraints(**constraints).model_dump(),
    )


def test_fixture_has_real_figis_and_unique_tickers() -> None:
    rows = universe_fixture()
    assert len(rows) >= 60
    assert all(len(r["figi"]) == 12 and r["figi"].startswith("BBG") for r in rows)
    assert len({r["ticker"] for r in rows}) == len(rows)
    assert {r["ticker"] for r in rows} >= {"AAPL", "NVDA", "TSLA", "SPY", "BIL", "SQQQ"}


def test_thesis_themes_match_stems_and_phrases() -> None:
    hits = thesis_themes("Humanoid robots are coming to every home; data center demand explodes")
    assert hits["robotics"] >= 2 and hits["humanoid"] >= 1 and hits["data-center"] >= 1


def test_heuristic_research_proposes_only_universe_tickers_with_roles() -> None:
    result = heuristic_research(
        take("Humanoid robots are coming to every home. Chip supply is the chokepoint."), universe()
    )
    tickers = {c.ticker for c in result.candidates}
    assert {"TSLA", "NVDA", "BOTZ"} <= tickers
    assert all(c.ticker in {r.ticker for r in universe()} for c in result.candidates)
    assert result.mode == "heuristic" and "Themes matched" in result.rationale_md
    roles = {c.ticker: c.role for c in result.candidates}
    assert roles["BOTZ"] == "enabler" and roles["TSLA"] == "pure_play"


def test_thin_thesis_falls_back_to_broad_market() -> None:
    result = heuristic_research(
        take("Something vague will happen eventually somewhere.", title="Vague"), universe()
    )
    assert {c.ticker for c in result.candidates} >= {"SPY", "QQQ"}


def test_guardrails_enforce_cash_cap_positions_and_exclusions() -> None:
    constraints = TakeConstraints(
        cash_buffer=0.1, max_single_name_weight=0.2, max_positions=5, exclusions=["Tesla", "ETF"]
    )
    candidates = [
        CandidateInstrument(ticker="TSLA", conviction=1.0),
        CandidateInstrument(ticker="NVDA", conviction=0.9),
        CandidateInstrument(ticker="BOTZ", conviction=0.9),
        CandidateInstrument(ticker="ISRG", conviction=0.6),
        CandidateInstrument(ticker="ROK", conviction=0.5),
        CandidateInstrument(ticker="TER", conviction=0.4),
        CandidateInstrument(ticker="SYM", conviction=0.3),
        CandidateInstrument(ticker="SQQQ", role="hedge", conviction=0.3),
        CandidateInstrument(ticker="FAKE", conviction=0.9),
    ]
    weights, notes = apply_guardrails(candidates, constraints, universe())
    tickers = [w.ticker for w in weights]
    assert "TSLA" not in tickers and "BOTZ" not in tickers, notes
    assert "SQQQ" not in tickers and "FAKE" not in tickers
    assert len(weights) == 5
    assert max(w.weight for w in weights) <= 0.2 + 1e-9
    assert abs(sum(w.weight for w in weights) - 0.9) < 1e-6
    assert any("not in the Hunch universe" in note for note in notes)
    assert any("leveraged or inverse" in note for note in notes)


def test_guardrails_hold_cap_overflow_as_cash_and_refuse_thin_baskets() -> None:
    constraints = TakeConstraints(cash_buffer=0.0, max_single_name_weight=0.1, max_positions=3)
    candidates = [CandidateInstrument(ticker=t, conviction=1.0) for t in ("NVDA", "AMD", "AVGO")]
    weights, notes = apply_guardrails(candidates, constraints, universe())
    assert abs(sum(w.weight for w in weights) - 0.3) < 1e-6
    assert any("uninvested" in note for note in notes)
    with pytest.raises(GuardrailError):
        apply_guardrails(candidates[:2], constraints, universe())


def test_propose_basket_in_heuristic_mode_is_complete_and_explainable() -> None:
    proposal = propose_basket(
        take("Humanoid robots are coming to every home.", cash_buffer=0.08),
        universe(),
        mode="heuristic",
    )
    assert proposal.weights and abs(proposal.cash_weight - 0.08) < 1e-6
    assert all(0 < w.weight <= 0.15 + 1e-9 for w in proposal.weights)
    assert proposal.research.mode == "heuristic"
    assert proposal.guardrail_notes[-1].endswith("cash.")
