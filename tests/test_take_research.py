"""Research and construction are independent steps (ADR 0008).

A research studies the target universe and is kept as a numbered row that decides no weight; a
build constructs the basket from one stored research and links the revision to it. A take that
was never researched cannot be built.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from tests.fakes import install_fake_rows
from tests.test_research import take as make_take
from tests.test_research import universe

from hunch.portfolios import build
from hunch.research import runs
from hunch.research.models import ResearchOutput
from hunch.takes import Take
from hunch.takes.research import TakeResearch
from hunch.takes.revisions import TakeRevision
from hunch.takes.services import TakeStateError

MOMENT = dt.datetime(2026, 10, 28, 15, 30, tzinfo=dt.timezone.utc)


@pytest.fixture
def rows(monkeypatch):
    return install_fake_rows(monkeypatch, Take, TakeResearch, TakeRevision)


@pytest.fixture
def stored_take(rows) -> Take:
    draft = make_take("Grid-scale batteries will carry the energy transition.", cash_buffer=0.08)
    return Take.create(**draft.model_dump())


@pytest.fixture
def researcher(monkeypatch):
    """The research step without a runtime: the fixture universe, bars recorded, no model."""
    calls: list[str] = []
    monkeypatch.setattr(runs, "ensure_universe", lambda: universe())
    monkeypatch.setattr(
        runs, "ensure_daily_bars", lambda figis, *, end=None: calls.append(f"bars:{len(figis)}")
    )
    real = runs.research_take

    def research_take(*args, **kwargs):
        calls.append("research")
        return real(*args, **kwargs)

    monkeypatch.setattr(runs, "research_take", research_take)
    return calls


def test_research_is_numbered_per_take_and_decides_no_weight(stored_take, researcher) -> None:
    first = runs.run_take_research(stored_take.uid, mode="heuristic", created_by="user")
    second = runs.run_take_research(stored_take.uid, mode="heuristic", now=MOMENT)

    assert (first.research.number, second.research.number) == (1, 2)
    assert first.research.created_by == "user" and second.research.created_by == "job"
    assert first.research.mode == "heuristic" and first.research.candidates_json
    assert all("weight" not in item for item in first.research.candidates_json)
    assert all(
        {"ticker", "role", "conviction"} <= set(item) for item in first.research.candidates_json
    )
    # The universe's bars are written before the quant evidence source reads them.
    assert researcher[:2] == [f"bars:{len(universe())}", "research"]
    assert [row.number for row in runs.take_research_rows(stored_take.uid)] == [1, 2]
    assert runs.latest_take_research(stored_take.uid).uid == second.research.uid


def test_research_refuses_missing_and_archived_takes(rows, stored_take, researcher) -> None:
    with pytest.raises(LookupError):
        runs.run_take_research(uuid.uuid4(), mode="heuristic")
    Take.update(stored_take.uid, status="archived")
    with pytest.raises(TakeStateError):
        runs.run_take_research(stored_take.uid, mode="heuristic")
    assert researcher == []


def test_stored_research_reads_back_as_the_researcher_returned_it(stored_take, researcher) -> None:
    result = runs.run_take_research(stored_take.uid, mode="heuristic")
    read = runs.research_output(TakeResearch.get_by_uid(result.research.uid))
    assert isinstance(read, ResearchOutput)
    assert read.model_dump() == result.output.model_dump()


def test_a_build_starts_from_the_latest_or_the_named_research_of_its_take(
    rows, stored_take, researcher
) -> None:
    with pytest.raises(TakeStateError, match="Research the take"):
        runs.research_for_build(stored_take.uid)
    first = runs.run_take_research(stored_take.uid, mode="heuristic").research
    second = runs.run_take_research(stored_take.uid, mode="heuristic").research
    assert runs.research_for_build(stored_take.uid).uid == second.uid
    assert runs.research_for_build(stored_take.uid, first.uid).uid == first.uid

    other = Take.create(**make_take("Humanoid robots at home.").model_dump())
    theirs = runs.run_take_research(other.uid, mode="heuristic").research
    with pytest.raises(LookupError):
        runs.research_for_build(stored_take.uid, theirs.uid)
    with pytest.raises(LookupError):
        runs.research_for_build(stored_take.uid, uuid.uuid4())


def test_build_constructs_from_the_stored_research_and_links_the_revision(
    monkeypatch, rows, stored_take, researcher
) -> None:
    kept = runs.run_take_research(stored_take.uid, mode="heuristic").research
    runs.run_take_research(stored_take.uid, mode="heuristic")  # a later one the build ignores

    constructed: list[tuple[object, ...]] = []
    real_construct = build.construct_basket

    def construct_basket(take, instruments, research):
        constructed.append((take.uid, research.mode, len(research.candidates)))
        return real_construct(take, instruments, research)

    monkeypatch.setattr(build, "construct_basket", construct_basket)
    monkeypatch.setattr(build, "ensure_universe", lambda: universe())
    monkeypatch.setattr(build, "ensure_daily_bars", lambda figis, *, end=None: None)
    monkeypatch.setattr(build, "take_universe", lambda uid, *extra: list(extra))
    monkeypatch.setattr(build, "ensure_trading_calendar", lambda: SimpleNamespace(uid=uuid.uuid4()))
    monkeypatch.setattr(build, "last_completed_session_close", lambda moment: moment)
    monkeypatch.setattr(
        build, "basket_signal", lambda uid, figis: SimpleNamespace(signal_uid="sig-1")
    )
    monkeypatch.setattr(build, "publish_basket_observation", lambda *args, **kwargs: None)
    portfolio_row = SimpleNamespace(uid=uuid.uuid4(), unique_identifier="hunch-take")
    monkeypatch.setattr(build, "Portfolio", SimpleNamespace(upsert=lambda **kwargs: portfolio_row))
    hunch_portfolios: list[dict] = []
    monkeypatch.setattr(
        build,
        "HunchPortfolio",
        SimpleNamespace(upsert=lambda **kwargs: hunch_portfolios.append(kwargs) or kwargs),
    )
    monkeypatch.setattr(build, "PortfolioGraph", lambda **kwargs: SimpleNamespace(run=lambda: {}))
    monkeypatch.setattr(build, "portfolio_value_points", lambda identifier: [])

    result = build.build_take(stored_take.uid, research_uid=kept.uid, now=MOMENT, created_by="user")

    assert constructed == [(stored_take.uid, "heuristic", len(kept.candidates_json))]
    assert result.research.uid == kept.uid
    assert result.revision.research_uid == kept.uid and result.revision.revision == 1
    assert result.revision.created_by == "user"
    assert result.revision.research_json["research_uid"] == str(kept.uid)
    assert result.revision.research_json["research_number"] == 1
    assert result.revision.weights_json and result.take.status == "built"
    assert hunch_portfolios[0]["metadata_json"]["research_uid"] == str(kept.uid)
    # Research recorded no model call in heuristic mode, so the revision cites none either.
    assert result.revision.inference_request_uids is None


def test_build_without_research_stops_before_touching_the_universe(
    monkeypatch, rows, stored_take
) -> None:
    touched: list[str] = []
    monkeypatch.setattr(build, "ensure_universe", lambda: touched.append("universe"))
    with pytest.raises(TakeStateError, match="Research the take"):
        build.build_take(stored_take.uid, now=MOMENT)
    assert touched == []
