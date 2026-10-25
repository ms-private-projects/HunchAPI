"""Research data shapes shared by the heuristic and inference researchers and the guardrails."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["pure_play", "supplier", "enabler", "hedge", "defensive"]

# Relative sizing by role, before conviction and constraints.
ROLE_MULTIPLIERS: dict[str, float] = {
    "pure_play": 1.0,
    "supplier": 0.8,
    "enabler": 0.6,
    "hedge": 0.5,
    "defensive": 0.5,
}


class ResearchError(RuntimeError):
    """Research could not produce a usable result."""


class ResearchBrief(BaseModel):
    """The thesis parsed into what the basket must express."""

    model_config = ConfigDict(extra="forbid")

    claims: list[str] = Field(default_factory=list, max_length=10)
    beneficiaries: list[str] = Field(default_factory=list, max_length=20)
    losers: list[str] = Field(default_factory=list, max_length=20)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    horizon_months: int = Field(default=12, ge=1, le=120)


class CandidateInstrument(BaseModel):
    """One instrument the research proposes, by ticker, with its role and case."""

    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=32)
    role: Role = "pure_play"
    case: str = Field(default="", max_length=1000)
    risks: list[str] = Field(default_factory=list, max_length=10)
    conviction: float = Field(default=0.5, ge=0.0, le=1.0)


class ResearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["inference", "heuristic"]
    brief: ResearchBrief
    candidates: list[CandidateInstrument]
    rationale_md: str = ""
    inference_request_uids: list[str] = Field(default_factory=list)
    conversation_uid: str | None = None


class BasketWeight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    figi: str
    ticker: str
    name: str
    weight: float = Field(ge=0.0, le=1.0)
    role: Role
    reason: str = ""


class BasketProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weights: list[BasketWeight]
    cash_weight: float = Field(ge=0.0, le=1.0)
    rationale_md: str
    research: ResearchOutput
    guardrail_notes: list[str] = Field(default_factory=list)

    def weights_by_figi(self) -> dict[str, float]:
        return {item.figi: item.weight for item in self.weights}


__all__ = [
    "ROLE_MULTIPLIERS",
    "BasketProposal",
    "BasketWeight",
    "CandidateInstrument",
    "ResearchBrief",
    "ResearchError",
    "ResearchOutput",
    "Role",
]
