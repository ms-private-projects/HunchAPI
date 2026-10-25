"""Deterministic research: match the thesis to instrument themes.

Used for tests, for local development without a model provider, and as the documented fallback.
It never invents instruments: candidates come from the universe's theme tags only.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

from hunch.instruments import HunchInstrument
from hunch.research.models import CandidateInstrument, ResearchBrief, ResearchOutput
from hunch.takes import Take

# Thesis words (stems) mapped to the universe's theme tags.
SYNONYMS: dict[str, tuple[str, ...]] = {
    "robot": ("robotics", "automation"),
    "humanoid": ("humanoid", "robotics"),
    "automat": ("automation", "robotics"),
    "ai": ("ai",),
    "artificial": ("ai",),
    "intelligen": ("ai",),
    "agent": ("ai-agents", "ai"),
    "llm": ("ai",),
    "model": ("ai",),
    "chip": ("semiconductors",),
    "semiconductor": ("semiconductors",),
    "gpu": ("semiconductors", "ai"),
    "compute": ("data-center", "semiconductors"),
    "data center": ("data-center",),
    "datacenter": ("data-center",),
    "cloud": ("cloud",),
    "software": ("software",),
    "saas": ("software",),
    "cyber": ("security",),
    "security": ("security",),
    "defen": ("defense",),
    "military": ("defense",),
    "drone": ("autonomy", "defense"),
    "autonom": ("autonomy",),
    "self-driving": ("autonomy",),
    "ev": ("ev",),
    "electric vehicle": ("ev",),
    "battery": ("batteries", "lithium", "energy-storage"),
    "lithium": ("lithium",),
    "copper": ("copper", "electrification"),
    "rare earth": ("rare-earths",),
    "magnet": ("magnets", "rare-earths"),
    "solar": ("solar", "renewables"),
    "renewable": ("renewables",),
    "nuclear": ("nuclear", "power"),
    "power": ("power", "grid"),
    "electric": ("electrification", "grid"),
    "grid": ("grid",),
    "utilit": ("utilities",),
    "oil": ("oil-gas",),
    "energy": ("energy",),
    "bank": ("banks", "financials"),
    "payment": ("payments",),
    "fintech": ("fintech", "payments"),
    "health": ("healthcare-services", "medtech"),
    "pharma": ("pharma",),
    "obesity": ("obesity",),
    "glp": ("obesity",),
    "surg": ("surgery", "robotics"),
    "medical": ("medtech",),
    "consumer": ("consumer-devices", "retail"),
    "retail": ("retail",),
    "housing": ("housing",),
    "home": ("housing", "consumer-devices"),
    "warehouse": ("warehouse", "logistics"),
    "logistic": ("logistics",),
    "factory": ("factory", "automation"),
    "manufactur": ("factory", "industrial"),
    "aerospace": ("aerospace",),
    "space": ("aerospace",),
    "agricult": ("agriculture",),
    "farm": ("agriculture",),
    "infrastructure": ("infrastructure",),
    "construct": ("construction",),
    "mining": ("mining",),
    "supply chain": ("supply-chain", "chokepoint"),
    "chokepoint": ("chokepoint",),
    "bottleneck": ("chokepoint",),
    "hedge": ("hedge",),
    "short": ("inverse", "hedge"),
    "recession": ("defensive", "treasuries"),
    "defensive": ("defensive",),
    "dividend": ("dividends",),
    "treasur": ("treasuries", "cash-like"),
    "cash": ("cash-like",),
    "small cap": ("small-caps",),
    "nasdaq": ("nasdaq-100",),
    "index": ("broad-market",),
    "market": ("broad-market",),
    "mega": ("mega-cap",),
    "quantum": ("quantum",),
    "ar": ("ar-vr",),
    "vr": ("ar-vr",),
    "social": ("social",),
    "advertis": ("advertising",),
    "search": ("search",),
    "device": ("consumer-devices",),
    "phone": ("mobile", "consumer-devices"),
    "network": ("networking",),
}

_WORD = re.compile(r"[a-z][a-z-]+")


def thesis_themes(text: str) -> Counter[str]:
    """Theme tags the thesis text points at, with how often each is hit."""
    lowered = text.lower()
    words = _WORD.findall(lowered)
    hits: Counter[str] = Counter()
    for stem, themes in SYNONYMS.items():
        if " " in stem:
            count = lowered.count(stem)
        elif len(stem) <= 3:
            # Short stems ("ai", "ev", "ar") match whole words only.
            count = sum(1 for word in words if word == stem)
        else:
            count = sum(1 for word in words if word.startswith(stem))
        for theme in themes:
            hits[theme] += count
    return +hits


def _role_for(instrument: HunchInstrument, score: float, matched: set[str]) -> str:
    if instrument.is_inverse:
        return "hedge"
    if "chokepoint" in matched or "supply-chain" in matched:
        return "supplier"
    if instrument.is_etf:
        return "enabler"
    if "defensive" in matched or "treasuries" in matched:
        return "defensive"
    return "pure_play" if score >= 4 else "enabler"


def heuristic_research(
    take: Take, instruments: Sequence[HunchInstrument], *, evidence: Sequence[Any] = ()
) -> ResearchOutput:
    text = f"{take.title}. {take.thesis_text}"
    themes = thesis_themes(text)
    brief = ResearchBrief(
        claims=[take.title],
        keywords=[theme for theme, _ in themes.most_common(12)],
        horizon_months=int((take.constraints_json or {}).get("horizon_months", 12)),
    )
    scored: list[tuple[float, HunchInstrument, set[str]]] = []
    for instrument in instruments:
        if not instrument.is_tradable:
            continue
        matched = {theme for theme in instrument.themes if themes.get(theme)}
        score = float(sum(2 * themes[theme] for theme in matched))
        if instrument.sector and instrument.sector.lower() in text.lower():
            score += 1.0
        if score > 0:
            scored.append((score, instrument, matched))
    scored.sort(key=lambda item: (-item[0], item[1].ticker))
    top = scored[:20]
    best = top[0][0] if top else 1.0
    by_figi: dict[str, list[Any]] = {}
    for item in evidence:
        by_figi.setdefault(item.figi, []).append(item)
    candidates = [
        CandidateInstrument(
            ticker=instrument.ticker,
            role=_role_for(instrument, score, matched),  # type: ignore[arg-type]
            case=f"Matches the thesis on {', '.join(sorted(matched)) or instrument.sector}.",
            conviction=round(min(1.0, score / best), 3),
            citations=[item.id for item in by_figi.get(instrument.figi, [])],
        )
        for score, instrument, matched in top
    ]
    if len(candidates) < 3:
        # Too thin a thesis to build on: broad market exposure keeps it investable.
        for ticker in ("SPY", "QQQ"):
            instrument = next((row for row in instruments if row.ticker == ticker), None)
            if instrument and all(c.ticker != ticker for c in candidates):
                candidates.append(
                    CandidateInstrument(
                        ticker=ticker,
                        role="enabler",
                        case="Broad market exposure while the thesis names few instruments.",
                        conviction=0.3,
                    )
                )
    chosen = {c.ticker for c in candidates}
    cited = [item for item in evidence if item.ticker in chosen]
    rationale = (
        f"## {take.title}\n\n{take.thesis_text}\n\n"
        f"**Themes matched:** {', '.join(brief.keywords) or 'none'}.\n\n"
        "**Basket:** "
        + "; ".join(
            f"{c.ticker} ({c.role.replace('_', ' ')})"
            + (f" [{', '.join(c.citations)}]" if c.citations else "")
            for c in candidates
        )
        + ".\n\n"
        + (
            "**Evidence:**\n" + "\n".join(f"- {item.line()}" for item in cited) + "\n\n"
            if cited
            else "**Evidence:** no external source is configured; only the universe tags were used.\n\n"
        )
        + "*Built by the deterministic theme matcher; no model was consulted.*"
    )
    return ResearchOutput(
        mode="heuristic",
        brief=brief,
        candidates=candidates,
        rationale_md=rationale,
        evidence=list(evidence),
    )


__all__ = ["SYNONYMS", "heuristic_research", "thesis_themes"]
