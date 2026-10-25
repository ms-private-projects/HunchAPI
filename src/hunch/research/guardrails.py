"""Deterministic guardrails: candidates in, constrained weights out.

Whatever the research proposed, the code decides: unknown or untradable tickers, exclusions,
leveraged and inverse products the person did not allow, the position count, the single-name
cap and the cash buffer are enforced here, and every decision is reported in the notes.
"""

from __future__ import annotations

from collections.abc import Sequence

from hunch.instruments import HunchInstrument
from hunch.research.models import ROLE_MULTIPLIERS, BasketWeight, CandidateInstrument
from hunch.takes.services import TakeConstraints

MINIMUM_POSITIONS = 3
WEIGHT_DECIMALS = 4


class GuardrailError(ValueError):
    """The constraints leave no investable basket."""


def _excluded(instrument: HunchInstrument, exclusions: Sequence[str]) -> str | None:
    haystack = {
        instrument.ticker.lower(),
        instrument.name.lower(),
        (instrument.sector or "").lower(),
        *instrument.themes,
    }
    for exclusion in exclusions:
        needle = exclusion.strip().lower()
        if not needle:
            continue
        if needle in haystack or any(needle in item for item in haystack if item):
            return exclusion
    return None


def _cap_and_normalise(
    raw: dict[str, float], investable: float, cap: float
) -> tuple[dict[str, float], float]:
    """Scale to the investable fraction, cap each name, redistribute; return weights and overflow."""
    total = sum(raw.values())
    if total <= 0:
        raise GuardrailError("The candidates carry no conviction to size by.")
    weights = {figi: investable * value / total for figi, value in raw.items()}
    capped: set[str] = set()
    for _ in range(len(weights) + 1):
        over = {figi: w for figi, w in weights.items() if w > cap + 1e-12 and figi not in capped}
        if not over:
            break
        excess = sum(w - cap for w in over.values())
        for figi in over:
            weights[figi] = cap
            capped.add(figi)
        free = {figi: w for figi, w in weights.items() if figi not in capped}
        free_total = sum(free.values())
        if free_total <= 0:
            return weights, excess
        for figi, w in free.items():
            weights[figi] = w + excess * w / free_total
    return weights, 0.0


def apply_guardrails(
    candidates: Sequence[CandidateInstrument],
    constraints: TakeConstraints,
    instruments: Sequence[HunchInstrument],
) -> tuple[list[BasketWeight], list[str]]:
    by_ticker = {row.ticker.upper(): row for row in instruments}
    notes: list[str] = []
    kept: list[tuple[CandidateInstrument, HunchInstrument]] = []
    seen: set[str] = set()
    for candidate in sorted(candidates, key=lambda item: -item.conviction):
        ticker = candidate.ticker.upper()
        instrument = by_ticker.get(ticker)
        if instrument is None:
            notes.append(f"{ticker}: not in the Hunch universe, dropped.")
            continue
        if instrument.figi in seen:
            continue
        if not instrument.is_tradable:
            notes.append(f"{ticker}: not tradable, dropped.")
            continue
        if (
            instrument.is_leveraged or instrument.is_inverse
        ) and not constraints.allow_leveraged_etf:
            notes.append(
                f"{ticker}: leveraged or inverse product not allowed by the take, dropped."
            )
            continue
        reason = _excluded(instrument, constraints.exclusions)
        if reason is not None:
            notes.append(f"{ticker}: excluded by the take ({reason}), dropped.")
            continue
        seen.add(instrument.figi)
        kept.append((candidate, instrument))
    if len(kept) > constraints.max_positions:
        dropped = kept[constraints.max_positions :]
        kept = kept[: constraints.max_positions]
        notes.append(
            f"Kept the {constraints.max_positions} highest-conviction names; dropped "
            + ", ".join(instrument.ticker for _, instrument in dropped)
            + "."
        )
    if len(kept) < MINIMUM_POSITIONS:
        raise GuardrailError(
            f"Only {len(kept)} investable instrument(s) remain after the take's constraints; "
            f"at least {MINIMUM_POSITIONS} are needed."
        )
    investable = max(0.0, 1.0 - constraints.cash_buffer)
    raw = {
        instrument.figi: max(candidate.conviction, 0.05) * ROLE_MULTIPLIERS[candidate.role]
        for candidate, instrument in kept
    }
    cap = min(constraints.max_single_name_weight, investable)
    weights, overflow = _cap_and_normalise(raw, investable, cap)
    if overflow > 1e-9:
        notes.append(
            f"The single-name cap of {constraints.max_single_name_weight:.0%} left "
            f"{overflow:.1%} uninvested; it is held as cash."
        )
    rounded = {figi: round(w, WEIGHT_DECIMALS) for figi, w in weights.items()}
    drift = round(sum(weights.values()) - sum(rounded.values()), WEIGHT_DECIMALS)
    if drift:
        largest = max(rounded, key=rounded.get)
        rounded[largest] = round(rounded[largest] + drift, WEIGHT_DECIMALS)
    basket = [
        BasketWeight(
            figi=instrument.figi,
            ticker=instrument.ticker,
            name=instrument.name,
            weight=rounded[instrument.figi],
            role=candidate.role,
            reason=candidate.case,
        )
        for candidate, instrument in kept
    ]
    basket.sort(key=lambda item: (-item.weight, item.ticker))
    notes.append(
        f"{len(basket)} positions, {sum(item.weight for item in basket):.1%} invested, "
        f"{1 - sum(item.weight for item in basket):.1%} cash."
    )
    return basket, notes


__all__ = ["GuardrailError", "MINIMUM_POSITIONS", "apply_guardrails"]
