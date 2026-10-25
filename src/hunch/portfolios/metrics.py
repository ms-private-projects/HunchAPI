"""Risk and return metrics of a value series (rebased NAV points since activation).

Pure functions over the `take_performance` rows: total return, annualised return and volatility,
Sharpe ratio (zero risk-free rate), maximum drawdown, best and worst day, and the count of
sessions. Metrics need at least two points; otherwise they are null and ``sessions`` says why.
"""

from __future__ import annotations

import math
from typing import Any

TRADING_DAYS = 252


def performance_metrics(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Metrics from ordered points with ``close`` (rebased) and optional ``return``."""
    closes = [float(p["close"]) for p in points if p.get("close") is not None]
    sessions = len(closes)
    if sessions < 2:
        return {
            "sessions": sessions,
            "total_return": round(closes[-1] - 1.0, 6) if closes else None,
            "annualised_return": None,
            "annualised_volatility": None,
            "sharpe_ratio": None,
            "max_drawdown": None,
            "best_day": None,
            "worst_day": None,
        }
    returns = [closes[i] / closes[i - 1] - 1.0 for i in range(1, sessions) if closes[i - 1] > 0]
    total = closes[-1] / closes[0] - 1.0
    years = (sessions - 1) / TRADING_DAYS
    annualised = (
        (closes[-1] / closes[0]) ** (1 / years) - 1.0 if years > 0 and closes[0] > 0 else None
    )
    mean = sum(returns) / len(returns)
    variance = (
        sum((r - mean) ** 2 for r in returns) / (len(returns) - 1) if len(returns) > 1 else 0.0
    )
    daily_vol = math.sqrt(variance)
    volatility = daily_vol * math.sqrt(TRADING_DAYS)
    sharpe = (mean / daily_vol) * math.sqrt(TRADING_DAYS) if daily_vol > 0 else None
    peak, drawdown = closes[0], 0.0
    for value in closes:
        peak = max(peak, value)
        if peak > 0:
            drawdown = min(drawdown, value / peak - 1.0)
    return {
        "sessions": sessions,
        "total_return": round(total, 6),
        "annualised_return": round(annualised, 6) if annualised is not None else None,
        "annualised_volatility": round(volatility, 6),
        "sharpe_ratio": round(sharpe, 4) if sharpe is not None else None,
        "max_drawdown": round(drawdown, 6),
        "best_day": round(max(returns), 6),
        "worst_day": round(min(returns), 6),
    }


__all__ = ["TRADING_DAYS", "performance_metrics"]
