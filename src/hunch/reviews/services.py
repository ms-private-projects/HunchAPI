"""The daily review of an active take: drift, thesis check, outcome, notification.

Practice takes rebalance to their basket every session in the model portfolio, so their review is
the thesis check and a status update. Funded takes also compare the account's actual weights with
the basket; when drift exceeds the thresholds, the funding module turns the review into a
``HunchRebalanceProposal`` through the ``proposal_factory`` hook (approval mode) or executes it
under the autopilot policy.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Callable, Sequence
from typing import Any

from hunch.community.notifications import notify
from hunch.profiles import utc_now
from hunch.research.models import ResearchError
from hunch.reviews import HunchDailyReview
from hunch.settings import MODEL_ROLE_REVIEW, research_mode
from hunch.takes import Take
from hunch.takes.services import TakeConstraints, TakeStateError

ACTIVE_STATUSES: tuple[str, ...] = ("active_practice", "funding", "active_funded")
MAX_DRIFT_THRESHOLD = 0.05
TOTAL_DRIFT_THRESHOLD = 0.10
VERDICTS: tuple[str, ...] = ("hold", "rebalance", "thesis_change")

ProposalFactory = Callable[..., Any]
REVIEW_NEWS_DAYS = 3


def conditions_of(constraints: TakeConstraints) -> list[str]:
    """The person's change-my-mind conditions, one per line."""
    text = constraints.change_my_mind or ""
    return [line.strip(" -•\t") for line in text.splitlines() if line.strip(" -•\t")]


THESIS_SYSTEM_PROMPT = """You are the daily reviewer of Hunch, a product that turns a person's \
investment thesis (their "take") into a basket of US-listed instruments.

You receive the thesis, the person's "what would change my mind" conditions, the current basket \
with roles, the performance since activation and the weight drift. Decide, in the person's \
interest and without hype:
- `hold`: nothing in the thesis or the basket needs attention.
- `rebalance`: the basket still expresses the thesis but weights drifted far enough to act.
- `thesis_change`: one of the person's conditions has plausibly triggered, or the basket no \
longer expresses the thesis; the person should review the take.
Reason only from what is given: the evidence list is the only news you have, cite its ids in \
square brackets (for example [E2]) and say when a judgement rests on general knowledge instead. \
Never promise returns. Answer with the JSON object described by the schema."""


def thesis_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["verdict", "reasoning", "triggered_conditions", "confidence"],
        "properties": {
            "verdict": {"type": "string", "enum": list(VERDICTS)},
            "reasoning": {"type": "string"},
            "triggered_conditions": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }


def target_weights(take: Take) -> dict[str, float]:
    """The latest basket of the take as {figi: weight}; empty before the first build."""
    from hunch.portfolios.build import take_revisions

    revisions = take_revisions(take.uid)
    if not revisions:
        return {}
    return {
        str(item["figi"]): float(item["weight"])
        for item in revisions[-1].weights_json
        if item.get("figi") is not None
    }


def model_weights(take: Take) -> dict[str, float]:
    """The model portfolio's latest weights as {figi: weight}."""
    from hunch.portfolios.build import take_weights

    return {str(row["figi"]): float(row["weight"]) for row in take_weights(take)}


def compute_drift(target: dict[str, float], current: dict[str, float]) -> dict[str, Any]:
    """Per-instrument and aggregate drift between a target basket and current weights."""
    figis = sorted(set(target) | set(current))
    positions = []
    for figi in figis:
        t = round(float(target.get(figi, 0.0)), 6)
        c = round(float(current.get(figi, 0.0)), 6)
        positions.append({"figi": figi, "target": t, "current": c, "drift": round(c - t, 6)})
    abs_drifts = [abs(p["drift"]) for p in positions]
    return {
        "max_abs_drift": round(max(abs_drifts), 6) if abs_drifts else 0.0,
        "total_abs_drift": round(sum(abs_drifts), 6),
        "target_invested": round(sum(target.values()), 6),
        "current_invested": round(sum(current.values()), 6),
        "positions": positions,
    }


def drift_exceeds(drift: dict[str, Any]) -> bool:
    return (
        float(drift.get("max_abs_drift", 0.0)) > MAX_DRIFT_THRESHOLD
        or float(drift.get("total_abs_drift", 0.0)) > TOTAL_DRIFT_THRESHOLD
    )


def heuristic_thesis_check(
    take: Take,
    drift: dict[str, Any],
    performance: dict[str, Any],
    evidence: Sequence[Any] = (),
) -> dict:
    """Deterministic review: drift decides; conditions and news are surfaced, never judged."""
    constraints = TakeConstraints.model_validate(take.constraints_json or {})
    verdict = "rebalance" if drift_exceeds(drift) else "hold"
    ret = performance.get("return_since_activation")
    news = [item for item in evidence if item.kind == "news"]
    reasoning = (
        f"Deterministic review. Max weight drift {drift['max_abs_drift']:.2%}, total "
        f"{drift['total_abs_drift']:.2%}; "
        + (f"return since activation {ret:+.2%}. " if ret is not None else "no value yet. ")
        + (
            f"{len(news)} recent news items are listed below for the person to judge."
            if news
            else "No news source is configured; the person's conditions are listed for review."
        )
    )
    return {
        "mode": "heuristic",
        "verdict": verdict,
        "reasoning": reasoning,
        "triggered_conditions": [],
        "conditions": conditions_of(constraints),
        "confidence": 0.5,
        "evidence": [item.model_dump(mode="json") for item in evidence],
    }


def inference_thesis_check(
    take: Take,
    drift: dict[str, Any],
    performance: dict[str, Any],
    basket: list[dict[str, Any]],
    *,
    review_date: dt.date,
    client: Any | None = None,
    evidence: Sequence[Any] = (),
) -> tuple[dict[str, Any], list[str]]:
    from hunch.research.inference import recorded_completion
    from hunch.research.sources import evidence_block

    constraints = TakeConstraints.model_validate(take.constraints_json or {})
    user = (
        f"# Take\n\nTitle: {take.title}\n\nThesis:\n{take.thesis_text}\n\n"
        f"# Conditions that would change the person's mind\n"
        f"{json.dumps(conditions_of(constraints), indent=2)}\n\n"
        f"# Basket\n{json.dumps(basket, indent=2)}\n\n"
        f"# Performance since activation\n{json.dumps(performance, indent=2, default=str)}\n\n"
        f"# Drift\n{json.dumps({k: v for k, v in drift.items() if k != 'positions'}, indent=2)}\n\n"
        f"# Evidence (cite by id; news is from the last {REVIEW_NEWS_DAYS} days)\n"
        f"{evidence_block(evidence)}\n\n"
        f"Review date: {review_date.isoformat()}. Return the JSON object described by the schema."
    )
    completion = recorded_completion(
        system=THESIS_SYSTEM_PROMPT,
        user=user,
        schema=thesis_schema(),
        operation="hunch-daily-review",
        metadata={"take_uid": str(take.uid), "review_date": review_date.isoformat()},
        idempotency_prefix=f"hunch-review-{take.uid}-{review_date.isoformat()}",
        timeout=120,
        client=client,
        what="review",
        role=MODEL_ROLE_REVIEW,
    )
    content = completion.content
    verdict = str(content.get("verdict") or "hold")
    if verdict not in VERDICTS:
        verdict = "hold"
    check = {
        "mode": "inference",
        "verdict": verdict,
        "reasoning": str(content.get("reasoning") or ""),
        "triggered_conditions": [str(c) for c in content.get("triggered_conditions") or []],
        "conditions": conditions_of(constraints),
        "confidence": float(content.get("confidence") or 0.0),
        "evidence": [item.model_dump(mode="json") for item in evidence],
    }
    return check, [completion.request_uid] if completion.request_uid else []


def performance_summary(take: Take) -> dict[str, Any]:
    from hunch.portfolios.build import take_performance

    points = take_performance(take)
    if not points:
        return {"points": 0, "return_since_activation": None, "as_of": None}
    last = points[-1]
    return {
        "points": len(points),
        "return_since_activation": round(float(last["close"]) - 1.0, 6),
        "as_of": last["time_index"],
    }


def review_evidence(take: Take, target: dict[str, float]) -> list[Any]:
    """Recent news (and the quant facts) for the basket's instruments; never fails a review."""
    from hunch.instruments.services import ensure_universe, instruments_by_figi
    from hunch.research import keywords_for
    from hunch.research.sources import collect_evidence, recent_news

    try:
        instruments = instruments_by_figi(ensure_universe())
        rows = [instruments[figi] for figi in target if figi in instruments]
        evidence = collect_evidence(rows, keywords_for(take))
    except Exception:  # pragma: no cover - sources are best effort
        return []
    since = utc_now() - dt.timedelta(days=REVIEW_NEWS_DAYS)
    news = recent_news(evidence, since=since)
    quant = [item for item in evidence if item.kind != "news"]
    return news + quant


def review_take(
    take_uid: uuid.UUID | str,
    *,
    review_date: dt.date | None = None,
    mode: str | None = None,
    current_weights: dict[str, float] | None = None,
    proposal_factory: ProposalFactory | None = None,
    client: Any | None = None,
) -> HunchDailyReview:
    """Review one active take for one date (idempotent per take and date)."""
    from hunch.portfolios.build import take_revisions

    take = Take.get_by_uid(uuid.UUID(str(take_uid)))
    if take is None:
        raise LookupError(f"Take {take_uid} does not exist.")
    if take.status not in ACTIVE_STATUSES:
        raise TakeStateError("Only activated takes are reviewed.")
    date = review_date or utc_now().date()
    revisions = take_revisions(take.uid)
    if not revisions:
        raise TakeStateError("The take has not been built.")
    latest = revisions[-1]
    target = target_weights(take)
    basket = [
        {k: item.get(k) for k in ("ticker", "weight", "role", "reason")}
        for item in latest.weights_json
    ]
    funded = take.status == "active_funded" and current_weights is not None
    current = current_weights if funded else model_weights(take)
    drift = compute_drift(target, current)
    if not funded:
        # The model portfolio returns to the basket every session; drift is informational.
        drift["basis"] = "model_portfolio"
    else:
        drift["basis"] = "account"
    performance = performance_summary(take)
    evidence = review_evidence(take, target)

    selected = mode or research_mode()
    request_uids: list[str] = []
    if selected == "inference":
        try:
            check, request_uids = inference_thesis_check(
                take, drift, performance, basket, review_date=date, client=client, evidence=evidence
            )
        except ResearchError as exc:
            check = heuristic_thesis_check(take, drift, performance, evidence)
            check["fallback"] = str(exc)
    else:
        check = heuristic_thesis_check(take, drift, performance, evidence)

    outcome = "hold"
    proposal_uid: uuid.UUID | None = None
    acting = funded and (drift_exceeds(drift) or check["verdict"] == "rebalance")
    if acting and proposal_factory is not None:
        trigger = "thesis" if check["verdict"] == "thesis_change" else "drift"
        proposal = proposal_factory(take=take, drift=drift, trigger=trigger, review_date=date)
        if proposal is not None:
            proposal_uid = proposal.uid
            outcome = "executed" if proposal.status in ("submitted", "filled") else "proposed"
    elif check["verdict"] == "thesis_change":
        outcome = "flagged"

    ret = performance.get("return_since_activation")
    summary = (
        f"## Daily review {date.isoformat()}\n\n"
        f"- Verdict: **{check['verdict']}** ({check['mode']})\n"
        f"- Return since activation: {ret:+.2%}\n"
        if ret is not None
        else f"## Daily review {date.isoformat()}\n\n- Verdict: **{check['verdict']}** ({check['mode']})\n"
    )
    summary += (
        f"- Drift ({drift['basis']}): max {drift['max_abs_drift']:.2%}, total "
        f"{drift['total_abs_drift']:.2%}\n- Outcome: {outcome}\n\n{check['reasoning']}\n"
    )
    if check.get("triggered_conditions"):
        summary += "\nTriggered conditions:\n" + "".join(
            f"- {c}\n" for c in check["triggered_conditions"]
        )

    review = HunchDailyReview.upsert(
        take_uid=take.uid,
        review_date=date,
        drift_json=drift,
        thesis_check_json=check,
        outcome=outcome,
        proposal_uid=proposal_uid,
        inference_request_uids=request_uids or None,
        summary_md=summary,
        created_at=utc_now(),
    )
    kind = {
        "hold": "review_hold",
        "flagged": "review_proposed",
        "proposed": "proposal_awaiting_approval",
        "executed": "proposal_executed",
    }[outcome]
    title = {
        "hold": f"{take.title}: holding steady",
        "flagged": f"{take.title}: your thesis conditions may have triggered",
        "proposed": f"{take.title}: a rebalance awaits your approval",
        "executed": f"{take.title}: autopilot rebalanced",
    }[outcome]
    notify(
        take.owner_user_uid,
        kind,
        title,
        body_md=summary,
        take_uid=take.uid,
        payload={
            "review_uid": str(review.uid),
            "review_date": date.isoformat(),
            "outcome": outcome,
            "verdict": check["verdict"],
            "proposal_uid": str(proposal_uid) if proposal_uid else None,
            "return_since_activation": ret,
        },
    )
    return review


def list_reviews(take_uid: uuid.UUID | str, *, limit: int = 30) -> list[HunchDailyReview]:
    rows = HunchDailyReview.filter(take_uid=uuid.UUID(str(take_uid)))
    rows.sort(key=lambda row: row.review_date, reverse=True)
    return rows[:limit]


__all__ = [
    "ACTIVE_STATUSES",
    "MAX_DRIFT_THRESHOLD",
    "TOTAL_DRIFT_THRESHOLD",
    "compute_drift",
    "drift_exceeds",
    "heuristic_thesis_check",
    "inference_thesis_check",
    "list_reviews",
    "model_weights",
    "performance_summary",
    "review_take",
    "target_weights",
    "thesis_schema",
]
