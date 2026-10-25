"""Research through Main Sequence recorded inference.

One structured completion per build: the model receives the thesis, the person's constraints and
the whole instrument universe, and must answer with a brief, candidates chosen from that universe
only, and a rationale. The platform records the request; its UID is kept on the revision.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any

from hunch.instruments import HunchInstrument
from hunch.research.models import (
    CandidateInstrument,
    ResearchBrief,
    ResearchError,
    ResearchOutput,
)
from hunch.settings import (
    inference_environment_uid,
    inference_model,
    inference_provider,
    inference_thinking,
)
from hunch.takes import Take
from hunch.takes.services import TakeConstraints

SYSTEM_PROMPT = """You are the research analyst of Hunch, a product that turns a person's \
investment thesis (their "take") into a diversified basket of US-listed instruments.

Rules:
- Choose instruments ONLY from the universe given to you, by their exact ticker. Never invent one.
- Express the thesis with pure plays, suppliers or chokepoints, secondary enablers, and, when the \
person's constraints allow leveraged or inverse products, at most one hedge.
- Respect the person's constraints: exclusions, risk level, horizon, number of positions.
- Prefer liquid, well-known names. Do not concentrate on a single name.
- Conviction is a relative sizing hint between 0 and 1.
- Write the rationale in Markdown for the person: the thesis in one paragraph, why these holdings \
express it, the roles, the main risks, and what would change your mind. Plain language, no hype.
- You are not an investment adviser; the person decides. Never promise returns.
"""


def _universe_block(instruments: Sequence[HunchInstrument]) -> str:
    lines = []
    for row in instruments:
        if not row.is_tradable:
            continue
        flags = [
            flag
            for flag, on in (
                ("etf", row.is_etf),
                ("leveraged", row.is_leveraged),
                ("inverse", row.is_inverse),
            )
            if on
        ]
        lines.append(
            f"- {row.ticker}: {row.name} | {row.sector or 'n/a'} | themes: {', '.join(row.themes)}"
            + (f" | {', '.join(flags)}" if flags else "")
        )
    return "\n".join(lines)


def response_schema(tickers: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["brief", "candidates", "rationale_md"],
        "properties": {
            "brief": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claims", "beneficiaries", "losers", "keywords"],
                "properties": {
                    "claims": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
                    "beneficiaries": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                    "losers": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
                    "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 30},
                },
            },
            "candidates": {
                "type": "array",
                "minItems": 3,
                "maxItems": 20,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["ticker", "role", "case", "risks", "conviction"],
                    "properties": {
                        "ticker": {"type": "string", "enum": list(tickers)},
                        "role": {
                            "type": "string",
                            "enum": ["pure_play", "supplier", "enabler", "hedge", "defensive"],
                        },
                        "case": {"type": "string", "maxLength": 600},
                        "risks": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                        "conviction": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
            },
            "rationale_md": {"type": "string", "maxLength": 6000},
        },
    }


def _user_prompt(
    take: Take, constraints: TakeConstraints, instruments: Sequence[HunchInstrument]
) -> str:
    return (
        f"# Take\n\nTitle: {take.title}\n\nThesis:\n{take.thesis_text}\n\n"
        f"# Constraints\n{json.dumps(constraints.model_dump(), indent=2)}\n\n"
        f"# Universe (choose tickers only from this list)\n{_universe_block(instruments)}\n\n"
        "Return the JSON object described by the schema."
    )


def inference_research(
    take: Take,
    instruments: Sequence[HunchInstrument],
    *,
    revision: int = 1,
    client: Any | None = None,
) -> ResearchOutput:
    """One recorded completion; raises ``ResearchError`` when no usable answer comes back."""
    from mainsequence.client import InferenceClient

    constraints = TakeConstraints.model_validate(take.constraints_json or {})
    tradable = [row for row in instruments if row.is_tradable]
    if not tradable:
        raise ResearchError("The instrument universe is empty.")
    environment = inference_environment_uid()
    inference = client or (
        InferenceClient(organization_environment_uid=environment)
        if environment
        else InferenceClient()
    )
    try:
        result = inference.complete(
            provider=inference_provider(),
            model=inference_model(),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": _user_prompt(take, constraints, tradable)},
            ],
            thinking_level=inference_thinking(),
            response_schema=response_schema([row.ticker for row in tradable]),
            metadata={
                "operation": "hunch-take-research",
                "take_uid": str(take.uid),
                "revision": revision,
            },
            idempotency_key=f"hunch-take-{take.uid}-revision-{revision}-{uuid.uuid4().hex[:8]}",
            timeout=240,
        )
    except Exception as exc:  # the client's own errors carry provider internals
        raise ResearchError(f"The research model call failed ({type(exc).__name__}).") from exc
    if result.status != "completed" or not result.content_available or not result.output:
        raise ResearchError(f"The research model call did not complete (status {result.status}).")
    content = result.output.get("content") if isinstance(result.output, dict) else None
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError as exc:
            raise ResearchError("The research model returned no JSON object.") from exc
    if not isinstance(content, dict):
        raise ResearchError("The research model returned no JSON object.")
    try:
        brief = ResearchBrief.model_validate(
            {**content.get("brief", {}), "horizon_months": constraints.horizon_months}
        )
        candidates = [CandidateInstrument.model_validate(item) for item in content["candidates"]]
    except Exception as exc:
        raise ResearchError("The research model answer does not match the contract.") from exc
    return ResearchOutput(
        mode="inference",
        brief=brief,
        candidates=candidates,
        rationale_md=str(content.get("rationale_md") or ""),
        inference_request_uids=[str(result.request_uid)] if result.request_uid else [],
        conversation_uid=str(result.conversation_uid) if result.conversation_uid else None,
    )


__all__ = ["SYSTEM_PROMPT", "inference_research", "response_schema"]
