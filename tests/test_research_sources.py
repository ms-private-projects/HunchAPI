"""Research sources ground builds and reviews with numbered, citable evidence."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from hunch.research.heuristic import heuristic_research
from hunch.research.inference import _user_prompt, response_schema
from hunch.research.sources import (
    Evidence,
    FinnhubSource,
    QuantFactsSource,
    collect_evidence,
    configured_sources,
    recent_news,
)
from hunch.takes import Take
from hunch.takes.services import TakeConstraints

NOW = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.timezone.utc)


def _instrument(figi: str, ticker: str, themes: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        figi=figi,
        ticker=ticker,
        name=ticker,
        sector="Information Technology",
        themes=themes,
        is_tradable=True,
        is_etf=False,
        is_leveraged=False,
        is_inverse=False,
    )


NVDA = _instrument("BBG000BBJQV0", "NVDA", ["ai", "semiconductors"])
TSLA = _instrument("BBG000N9MNX3", "TSLA", ["robotics", "humanoid", "ev"])


def test_quant_source_turns_bar_facts_into_evidence() -> None:
    facts = {
        "BBG000BBJQV0": {
            "one_year_return": 0.42,
            "annualised_volatility": 0.51,
            "average_daily_volume": 250_000_000,
        }
    }
    with patch("hunch.market_data.quantitative_facts", return_value=facts):
        items = QuantFactsSource().evidence([NVDA, TSLA], [])
    assert len(items) == 1 and items[0].kind == "quant" and "+42.0%" in items[0].title


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, *, params, timeout):
        self.calls.append((url, params))
        if url.endswith("/company-news"):
            body = [
                {
                    "headline": "NVIDIA ships new chip",
                    "summary": "Blackwell successor",
                    "source": "Reuters",
                    "url": "https://r.example/1",
                    "datetime": int(NOW.timestamp()) - 3600,
                },
                {
                    "headline": "Old news",
                    "summary": "",
                    "source": "X",
                    "url": "https://r.example/0",
                    "datetime": int(NOW.timestamp()) - 86400 * 20,
                },
            ]
        else:
            body = {
                "metric": {
                    "peTTM": 55.2,
                    "beta": 1.7,
                    "52WeekHigh": 200.0,
                    "revenueGrowthTTMYoy": None,
                }
            }
        return SimpleNamespace(json=lambda: body, raise_for_status=lambda: None)


def test_finnhub_source_reads_news_and_fundamentals_by_ticker() -> None:
    session = FakeSession()
    items = FinnhubSource("k", session=session, now=NOW).evidence([NVDA], ["ai"])
    kinds = [item.kind for item in items]
    assert kinds == ["news", "news", "fundamental"]
    assert items[0].title == "NVIDIA ships new chip" and items[0].url == "https://r.example/1"
    assert "P/E 55.20" in items[2].title and "revenue growth" not in items[2].title
    assert all("token" in params for _, params in session.calls)
    since = NOW - dt.timedelta(days=3)
    assert [item.title for item in recent_news(items, since=since)] == ["NVIDIA ships new chip"]


def test_collect_evidence_numbers_and_deduplicates(monkeypatch) -> None:
    class Dup:
        name = "dup"

        def evidence(self, instruments, keywords):
            item = Evidence(figi=NVDA.figi, ticker="NVDA", kind="news", title="Same", source="s")
            return [item, item]

    class Broken:
        name = "broken"

        def evidence(self, instruments, keywords):
            raise RuntimeError("down")

    items = collect_evidence([NVDA], sources=[Dup(), Broken()])
    assert [item.id for item in items] == ["E1"]
    monkeypatch.setenv("HUNCH_RESEARCH_SOURCES", "quant,finnhub,unknown")
    monkeypatch.delenv("HUNCH_FINNHUB_API_KEY", raising=False)
    assert [s.name for s in configured_sources()] == ["quant"]
    monkeypatch.setenv("HUNCH_FINNHUB_API_KEY", "key")
    assert [s.name for s in configured_sources()] == ["quant", "finnhub"]


def test_prompt_and_schema_carry_the_evidence_and_citations() -> None:
    take = Take(
        uid=uuid.uuid4(),
        owner_user_uid="u",
        title="Robots",
        thesis_text="Humanoid robots everywhere.",
    )
    evidence = [
        Evidence(
            id="E1",
            figi=TSLA.figi,
            ticker="TSLA",
            kind="news",
            title="Optimus demo",
            source="Reuters",
        )
    ]
    prompt = _user_prompt(take, TakeConstraints(), [NVDA, TSLA], evidence)
    assert "[E1] TSLA news (Reuters): Optimus demo" in prompt
    candidate = response_schema(["NVDA", "TSLA"])["properties"]["candidates"]["items"]
    assert "citations" in candidate["required"]


def test_heuristic_cites_the_evidence_of_its_picks() -> None:
    take = Take(
        uid=uuid.uuid4(),
        owner_user_uid="u",
        title="Robots",
        thesis_text="Humanoid robots in every home.",
    )
    evidence = [
        Evidence(
            id="E1",
            figi=TSLA.figi,
            ticker="TSLA",
            kind="quant",
            title="1y return +10%",
            source="hunch bars",
        ),
        Evidence(
            id="E2",
            figi=NVDA.figi,
            ticker="NVDA",
            kind="quant",
            title="1y return +40%",
            source="hunch bars",
        ),
    ]
    output = heuristic_research(take, [NVDA, TSLA], evidence=evidence)
    by_ticker = {c.ticker: c for c in output.candidates}
    assert by_ticker["TSLA"].citations == ["E1"]
    assert "[E1] TSLA quant" in output.rationale_md and output.evidence == evidence
