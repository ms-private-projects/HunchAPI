"""Analysis-only answers about a take: read it, ask one bounded question, answer the person."""

from hunch.analysis.services import (
    ClaimAssessment,
    ThesisCritique,
    critique_thesis,
    heuristic_critique,
    inference_critique,
)

__all__ = [
    "ClaimAssessment",
    "ThesisCritique",
    "critique_thesis",
    "heuristic_critique",
    "inference_critique",
]
