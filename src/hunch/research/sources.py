"""Research sources: evidence that grounds a build or a review, with citations.

A source turns instruments and the thesis keywords into ``Evidence`` items the researcher cites
(``[E3]``) and the revision stores. Two sources ship: ``quant`` (facts computed from the stored
daily bars, always available) and ``finnhub`` (company news and basic financials from Finnhub's
API, when ``HUNCH_FINNHUB_API_KEY`` is set). Nothing here invents evidence: without a configured
news source, research says so and cites only the quantitative facts.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from collections.abc import Sequence
from typing import Any, Literal, Protocol

import requests
from pydantic import BaseModel, ConfigDict, Field

from hunch.instruments import HunchInstrument

logger = logging.getLogger(__name__)
UTC = dt.timezone.utc

EvidenceKind = Literal["quant", "news", "fundamental"]
DEFAULT_SOURCES = "quant"
FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
NEWS_LOOKBACK_DAYS = 14
NEWS_PER_INSTRUMENT = 3


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    figi: str
    ticker: str
    kind: EvidenceKind
    title: str = Field(max_length=300)
    summary: str = Field(default="", max_length=1000)
    source: str
    url: str | None = None
    published_at: dt.datetime | None = None

    def line(self) -> str:
        when = f", {self.published_at.date().isoformat()}" if self.published_at else ""
        text = f"[{self.id}] {self.ticker} {self.kind} ({self.source}{when}): {self.title}"
        if self.summary:
            text += f" — {self.summary}"
        return text


class ResearchSource(Protocol):
    name: str

    def evidence(
        self, instruments: Sequence[HunchInstrument], keywords: Sequence[str]
    ) -> list[Evidence]: ...


class QuantFactsSource:
    """Facts from the stored daily bars: one-year return, volatility, average volume."""

    name = "quant"

    def evidence(
        self, instruments: Sequence[HunchInstrument], keywords: Sequence[str]
    ) -> list[Evidence]:
        from hunch.market_data import quantitative_facts

        facts = quantitative_facts([row.figi for row in instruments])
        items: list[Evidence] = []
        for row in instruments:
            fact = facts.get(row.figi)
            if not fact:
                continue
            items.append(
                Evidence(
                    figi=row.figi,
                    ticker=row.ticker,
                    kind="quant",
                    title=(
                        f"1y return {fact['one_year_return']:+.1%}, annualised volatility "
                        f"{fact['annualised_volatility']:.0%}, average daily volume "
                        f"{fact['average_daily_volume']:,.0f}"
                    ),
                    summary="Computed from the stored daily bars.",
                    source="hunch bars",
                )
            )
        return items


class FinnhubSource:
    """Company news and basic financials from Finnhub (https://finnhub.io), by ticker."""

    name = "finnhub"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = FINNHUB_BASE_URL,
        session: requests.Session | None = None,
        now: dt.datetime | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._key = api_key
        self._base = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._now = now
        self._timeout = timeout

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        response = self._session.get(
            f"{self._base}{path}",
            params={**params, "token": self._key},
            timeout=self._timeout,
        )
        response.raise_for_status()
        return response.json()

    def evidence(
        self, instruments: Sequence[HunchInstrument], keywords: Sequence[str]
    ) -> list[Evidence]:
        now = self._now or dt.datetime.now(UTC)
        start = (now - dt.timedelta(days=NEWS_LOOKBACK_DAYS)).date().isoformat()
        items: list[Evidence] = []
        for row in instruments:
            try:
                news = self._get(
                    "/company-news",
                    {"symbol": row.ticker, "from": start, "to": now.date().isoformat()},
                )
            except (requests.RequestException, ValueError) as exc:
                logger.warning("Finnhub news failed for %s: %s", row.ticker, type(exc).__name__)
                news = []
            for article in sorted(
                (a for a in news if isinstance(a, dict)),
                key=lambda a: a.get("datetime") or 0,
                reverse=True,
            )[:NEWS_PER_INSTRUMENT]:
                stamp = article.get("datetime")
                items.append(
                    Evidence(
                        figi=row.figi,
                        ticker=row.ticker,
                        kind="news",
                        title=str(article.get("headline") or "")[:300],
                        summary=str(article.get("summary") or "")[:1000],
                        source=str(article.get("source") or "finnhub"),
                        url=article.get("url"),
                        published_at=dt.datetime.fromtimestamp(stamp, UTC) if stamp else None,
                    )
                )
            try:
                metrics = (
                    self._get("/stock/metric", {"symbol": row.ticker, "metric": "all"}) or {}
                ).get("metric") or {}
            except (requests.RequestException, ValueError) as exc:
                logger.warning("Finnhub metrics failed for %s: %s", row.ticker, type(exc).__name__)
                metrics = {}
            facts = {
                "P/E": metrics.get("peTTM"),
                "P/S": metrics.get("psTTM"),
                "beta": metrics.get("beta"),
                "52w high": metrics.get("52WeekHigh"),
                "52w low": metrics.get("52WeekLow"),
                "revenue growth": metrics.get("revenueGrowthTTMYoy"),
            }
            present = {k: v for k, v in facts.items() if isinstance(v, (int, float))}
            if present:
                items.append(
                    Evidence(
                        figi=row.figi,
                        ticker=row.ticker,
                        kind="fundamental",
                        title=", ".join(f"{k} {v:,.2f}" for k, v in present.items()),
                        summary="Trailing-twelve-month figures from Finnhub basic financials.",
                        source="finnhub",
                        url=f"https://finnhub.io/api/v1/stock/metric?symbol={row.ticker}",
                        published_at=now,
                    )
                )
        return items


def configured_sources(*, names: Sequence[str] | None = None) -> list[ResearchSource]:
    """The sources named by ``HUNCH_RESEARCH_SOURCES`` (comma separated) that are usable."""
    wanted = (
        list(names)
        if names is not None
        else [
            n.strip()
            for n in os.environ.get("HUNCH_RESEARCH_SOURCES", DEFAULT_SOURCES).split(",")
            if n.strip()
        ]
    )
    sources: list[ResearchSource] = []
    for name in wanted:
        if name == "quant":
            sources.append(QuantFactsSource())
        elif name == "finnhub":
            key = os.environ.get("HUNCH_FINNHUB_API_KEY", "").strip()
            if key:
                sources.append(FinnhubSource(key))
            else:
                logger.warning(
                    "HUNCH_RESEARCH_SOURCES names finnhub but HUNCH_FINNHUB_API_KEY is empty."
                )
        else:
            logger.warning("Unknown research source %r ignored.", name)
    return sources


def collect_evidence(
    instruments: Sequence[HunchInstrument],
    keywords: Sequence[str] = (),
    *,
    sources: Sequence[ResearchSource] | None = None,
    limit: int = 120,
) -> list[Evidence]:
    """Evidence from every configured source, numbered ``E1..En`` and capped."""
    items: list[Evidence] = []
    for source in sources if sources is not None else configured_sources():
        try:
            items.extend(source.evidence(instruments, keywords))
        except Exception as exc:  # a source must never fail a build
            logger.warning("Research source %s failed: %s", source.name, type(exc).__name__)
    seen: set[tuple[str, str, str]] = set()
    numbered: list[Evidence] = []
    for item in items:
        key = (item.figi, item.kind, item.title)
        if key in seen:
            continue
        seen.add(key)
        numbered.append(item.model_copy(update={"id": f"E{len(numbered) + 1}"}))
        if len(numbered) >= limit:
            break
    return numbered


def evidence_block(evidence: Sequence[Evidence]) -> str:
    if not evidence:
        return "No external evidence source is configured; only the universe facts above apply."
    return "\n".join(item.line() for item in evidence)


def recent_news(evidence: Sequence[Evidence], *, since: dt.datetime) -> list[Evidence]:
    return [
        item
        for item in evidence
        if item.kind == "news" and item.published_at is not None and item.published_at >= since
    ]


__all__ = [
    "DEFAULT_SOURCES",
    "Evidence",
    "FinnhubSource",
    "QuantFactsSource",
    "ResearchSource",
    "collect_evidence",
    "configured_sources",
    "evidence_block",
    "recent_news",
]
