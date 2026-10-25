"""Research: from a thesis to candidate instruments with roles, then to guarded weights.

The model proposes; code decides. ``research_take`` returns candidates and a rationale from the
configured mode (recorded inference, or the deterministic heuristic), and ``apply_guardrails``
turns them into weights that respect the person's constraints.
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
    revision: int = 1,
) -> ResearchOutput:
    """Candidates and rationale for the take, in the requested or configured mode."""
    selected = mode or research_mode()
    tradable = [row for row in instruments if row.is_tradable]
    evidence: list[Evidence] = collect_evidence(tradable, keywords_for(take))
    if selected == "heuristic":
        return heuristic_research(take, instruments, evidence=evidence)
    from hunch.research.inference import inference_research

    return inference_research(take, instruments, revision=revision, evidence=evidence)


def keywords_for(take: Take) -> list[str]:
    from hunch.research.heuristic import thesis_themes

    return [
        theme for theme, _ in thesis_themes(f"{take.title}. {take.thesis_text}").most_common(12)
    ]


def propose_basket(
    take: Take,
    instruments: Sequence[HunchInstrument],
    *,
    mode: str | None = None,
    revision: int = 1,
) -> BasketProposal:
    """Research the take and apply its constraints: the complete, explainable basket."""
    constraints = TakeConstraints.model_validate(take.constraints_json or {})
    research = research_take(take, instruments, mode=mode, revision=revision)
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
    "propose_basket",
    "research_take",
]
