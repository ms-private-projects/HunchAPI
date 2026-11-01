"""Research and construction: two independent steps from a thesis to a basket (ADR 0008).

The model proposes; code decides. ``research_take`` studies the target universe and returns the
candidate instruments with their roles and conviction, a brief and a rationale, from the
configured mode (recorded inference on the `research` role, or the deterministic heuristic); it
decides no weight. ``construct_basket`` is portfolio construction: it turns one research's
candidates into weights that respect the person's constraints through ``apply_guardrails``, with
no model call. ``hunch.research.runs`` stores each research; ``hunch.portfolios.build`` builds the
portfolio from a stored one.
"""

from __future__ import annotations

from collections.abc import Sequence

from hunch.instruments import HunchInstrument
from hunch.research.guardrails import GuardrailError, apply_guardrails
from hunch.research.heuristic import heuristic_research
from hunch.research.models import (
    BasketProposal,
    BasketWeight,
    CandidateInstrument,
    ResearchBrief,
    ResearchError,
    ResearchOutput,
)
from hunch.research.sources import Evidence, collect_evidence
from hunch.settings import research_mode
from hunch.takes import Take
from hunch.takes.services import TakeConstraints


def research_take(
    take: Take,
    instruments: Sequence[HunchInstrument],
    *,
    mode: str | None = None,
    number: int = 1,
) -> ResearchOutput:
    """Candidates and rationale for the take, in the requested or configured mode.

    `number` is the research's ordinal for the take; it makes the recorded call idempotent per
    research and appears in its metadata.
    """
    selected = mode or research_mode()
    tradable = [row for row in instruments if row.is_tradable]
    evidence: list[Evidence] = collect_evidence(tradable, keywords_for(take))
    if selected == "heuristic":
        return heuristic_research(take, instruments, evidence=evidence)
    from hunch.research.inference import inference_research

    return inference_research(take, instruments, number=number, evidence=evidence)


def keywords_for(take: Take) -> list[str]:
    from hunch.research.heuristic import thesis_themes

    return [
        theme for theme, _ in thesis_themes(f"{take.title}. {take.thesis_text}").most_common(12)
    ]


def construct_basket(
    take: Take,
    instruments: Sequence[HunchInstrument],
    research: ResearchOutput,
) -> BasketProposal:
    """Portfolio construction: the research's candidates under the take's constraints.

    Deterministic and explainable: exclusions, tradability, leveraged products, the position
    count, the single-name cap and the cash buffer are enforced by the guardrails, which report
    every decision. No model is called.
    """
    constraints = TakeConstraints.model_validate(take.constraints_json or {})
    weights, notes = apply_guardrails(research.candidates, constraints, instruments)
    return BasketProposal(
        weights=weights,
        cash_weight=round(1.0 - sum(item.weight for item in weights), 6),
        rationale_md=research.rationale_md,
        research=research,
        guardrail_notes=notes,
    )


__all__ = [
    "BasketProposal",
    "BasketWeight",
    "CandidateInstrument",
    "GuardrailError",
    "ResearchBrief",
    "ResearchError",
    "ResearchOutput",
    "apply_guardrails",
    "construct_basket",
    "research_take",
]
