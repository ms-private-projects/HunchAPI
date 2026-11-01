"""Analysis-only model calls: read a take, ask one bounded question, answer the person.

An analysis never changes Hunch state and never trades. Each one is a single recorded completion
on the `analysis` model role (``hunch.settings.model_role``), validated against a JSON schema, so a
deployment can run analysis on a different model from research and reviews. In `heuristic`
research mode a deterministic reading answers instead, so the local stack and the tests need no
provider. The first analysis is the thesis critique: what a take claims, what it assumes, what
would show it wrong, and where it strains against its own constraints.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hunch.research.heuristic import thesis_themes
from hunch.research.inference import recorded_completion
from hunch.research.models import ResearchError
from hunch.reviews.services import conditions_of
from hunch.settings import MODEL_ROLE_ANALYSIS, research_mode
from hunch.takes import Take
from hunch.takes.services import TakeConstraints

Clarity = Literal["clear", "partly_clear", "vague"]
Strength = Literal["strong", "moderate", "weak"]
CLARITIES: tuple[str, ...] = ("clear", "partly_clear", "vague")
STRENGTHS: tuple[str, ...] = ("strong", "moderate", "weak")

MAX_ITEMS = 8
MAX_TEXT = 600
MAX_SUMMARY = 2000
ANALYSIS_TIMEOUT_SECONDS = 90

# Deterministic reading: wording that hedges a claim, that names a period, or that names a loser.
HEDGES = frozenset({"maybe", "might", "could", "eventually", "possibly", "perhaps", "someday"})
TIME_WORDS = re.compile(r"\b(decades?|years?|months?|quarters?|20\d\d)\b")
LOSER_WORDS = re.compile(
    r"\b(los(e|es|ers?|ing)|declines?|replac(e|es|ing)|disrupt(s|ed|ing)?|shrinks?|obsolete"
    r"|hurts?|expense)\b"
)
HEDGING_WORDS = re.compile(r"\b(short|shorting|hedge|hedged|inverse|bet against)\b")
_SENTENCE = re.compile(r"[^.!?;\n]+[.!?;]?")


class ClaimAssessment(BaseModel):
    """One claim the thesis makes and how much weight it can carry."""

    model_config = ConfigDict(extra="forbid")

    claim: str = Field(min_length=1, max_length=MAX_TEXT)
    strength: Strength
    note: str = Field(default="", max_length=MAX_TEXT)


class ThesisCritique(BaseModel):
    """The critique of one take's thesis, from the analysis model or the deterministic reading."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["inference", "heuristic"]
    summary: str = Field(max_length=MAX_SUMMARY)
    clarity: Clarity
    claims: list[ClaimAssessment] = Field(default_factory=list, max_length=MAX_ITEMS)
    assumptions: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    counterarguments: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    risks: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    suggested_conditions: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    constraint_notes: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    questions: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    provider: str | None = None
    model: str | None = None
    inference_request_uids: list[str] = Field(default_factory=list)
    conversation_uid: str | None = None


SYSTEM_PROMPT = """You are the thesis critic of Hunch, a product that turns a person's \
investment thesis (their "take") into a basket of US-listed instruments.

You receive one thesis, the constraints the person set for the basket, and the themes Hunch \
recognises in the text. Critique the thesis for the person, in their interest and without hype:
- Restate it in one paragraph as you understand it.
- Judge how clearly it is stated: `clear`, `partly_clear` or `vague`.
- List its claims one by one with the strength each can carry (`strong`, `moderate`, `weak`) and \
why, from general knowledge. You have no news, prices or data: say when you are unsure and never \
invent figures, dates or sources.
- Name the assumptions the thesis relies on without saying so, the strongest counterarguments, and \
the risks of expressing it with listed equities over the person's horizon.
- Suggest conditions that would show the thesis is wrong, written so the person could check them; \
this matters most when they gave none.
- Note any tension between the thesis and the constraints: horizon, number of positions, \
exclusions, leveraged or inverse products, risk level, cash buffer.
- Ask the questions that would sharpen the thesis.
Plain language, no jargon. You are not an investment adviser and nothing you write is a \
recommendation to buy or sell; the person decides. Answer with the JSON object described by the \
schema."""


def _strings(maximum: int = MAX_ITEMS) -> dict[str, Any]:
    return {
        "type": "array",
        "maxItems": maximum,
        "items": {"type": "string", "maxLength": MAX_TEXT},
    }


def critique_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "summary",
            "clarity",
            "claims",
            "assumptions",
            "counterarguments",
            "risks",
            "suggested_conditions",
            "constraint_notes",
            "questions",
        ],
        "properties": {
            "summary": {"type": "string", "maxLength": MAX_SUMMARY},
            "clarity": {"type": "string", "enum": list(CLARITIES)},
            "claims": {
                "type": "array",
                "maxItems": MAX_ITEMS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["claim", "strength", "note"],
                    "properties": {
                        "claim": {"type": "string", "maxLength": MAX_TEXT},
                        "strength": {"type": "string", "enum": list(STRENGTHS)},
                        "note": {"type": "string", "maxLength": MAX_TEXT},
                    },
                },
            },
            "assumptions": _strings(),
            "counterarguments": _strings(),
            "risks": _strings(),
            "suggested_conditions": _strings(),
            "constraint_notes": _strings(),
            "questions": _strings(),
        },
    }


def _themes(take: Take) -> list[str]:
    hits = thesis_themes(f"{take.title}. {take.thesis_text}")
    return [theme for theme, _ in hits.most_common(MAX_ITEMS)]


def _constraints(take: Take) -> TakeConstraints:
    return TakeConstraints.model_validate(take.constraints_json or {})


def _user_prompt(take: Take, constraints: TakeConstraints, themes: list[str]) -> str:
    conditions = conditions_of(constraints)
    return (
        f"# Take\n\nTitle: {take.title}\n\nThesis:\n{take.thesis_text}\n\n"
        f"# Constraints\n{json.dumps(constraints.model_dump(), indent=2)}\n\n"
        f"# Conditions the person said would change their mind\n"
        f"{json.dumps(conditions, indent=2) if conditions else 'None given.'}\n\n"
        f"# Themes Hunch recognises in the text\n{', '.join(themes) or 'none'}\n\n"
        "Return the JSON object described by the schema."
    )


def _clip_text(value: Any, limit: int) -> str:
    return str(value if value is not None else "")[:limit]


def _clip_list(values: Any, limit: int = MAX_ITEMS) -> list[str]:
    if not isinstance(values, list):
        return []
    return [_clip_text(item, MAX_TEXT) for item in values[:limit] if str(item or "").strip()]


def _clip_claims(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    claims = []
    for item in values[:MAX_ITEMS]:
        if not isinstance(item, dict) or not str(item.get("claim") or "").strip():
            continue
        claims.append(
            {
                "claim": _clip_text(item.get("claim"), MAX_TEXT),
                "strength": item.get("strength"),
                "note": _clip_text(item.get("note"), MAX_TEXT),
            }
        )
    return claims


def inference_critique(take: Take, *, client: Any | None = None) -> ThesisCritique:
    """One recorded completion on the analysis role; raises ``ResearchError`` on any failure."""
    constraints = _constraints(take)
    themes = _themes(take)
    completion = recorded_completion(
        system=SYSTEM_PROMPT,
        user=_user_prompt(take, constraints, themes),
        schema=critique_schema(),
        operation="hunch-thesis-critique",
        metadata={"take_uid": str(take.uid)},
        idempotency_prefix=f"hunch-critique-{take.uid}",
        timeout=ANALYSIS_TIMEOUT_SECONDS,
        client=client,
        what="analysis",
        role=MODEL_ROLE_ANALYSIS,
    )
    content = completion.content
    # A provider that does not enforce the schema's sizes still gets a bounded answer.
    try:
        return ThesisCritique(
            mode="inference",
            summary=_clip_text(content.get("summary"), MAX_SUMMARY),
            clarity=content.get("clarity"),
            claims=_clip_claims(content.get("claims")),
            assumptions=_clip_list(content.get("assumptions")),
            counterarguments=_clip_list(content.get("counterarguments")),
            risks=_clip_list(content.get("risks")),
            suggested_conditions=_clip_list(content.get("suggested_conditions")),
            constraint_notes=_clip_list(content.get("constraint_notes")),
            questions=_clip_list(content.get("questions")),
            provider=completion.provider,
            model=completion.model,
            inference_request_uids=[completion.request_uid] if completion.request_uid else [],
            conversation_uid=completion.conversation_uid,
        )
    except ValidationError as exc:
        raise ResearchError("The analysis model answer does not match the contract.") from exc


def _sentences(text: str) -> list[str]:
    found = [item.strip(" \t") for item in _SENTENCE.findall(text)]
    return [item for item in found if len(item.strip(".!?; ")) > 3][:MAX_ITEMS]


def _overlaps(exclusion: str, themes: Iterable[str]) -> str | None:
    lowered = exclusion.lower().replace(" ", "-")
    for theme in themes:
        if lowered in theme or theme in lowered:
            return theme
    return None


def heuristic_critique(take: Take) -> ThesisCritique:
    """A deterministic reading: structure and constraints only, no judgement of the claims."""
    constraints = _constraints(take)
    themes = _themes(take)
    lowered = f"{take.title}. {take.thesis_text}".lower()
    conditions = conditions_of(constraints)
    sentences = _sentences(take.thesis_text)

    claims = []
    for sentence in sentences:
        hedged = any(word in HEDGES for word in re.findall(r"[a-z']+", sentence.lower()))
        claims.append(
            ClaimAssessment(
                claim=sentence[:MAX_TEXT],
                strength="weak" if hedged else "moderate",
                note=(
                    "Hedged wording: stated as a possibility."
                    if hedged
                    else "Stated as a fact; this deterministic reading checked no evidence."
                ),
            )
        )
    clarity: Clarity = (
        "clear" if len(themes) >= 3 and sentences else "partly_clear" if themes else "vague"
    )
    summary = (
        "Deterministic reading, without the analysis model. The thesis points at "
        + (", ".join(themes) if themes else "no theme Hunch recognises")
        + f" over a {constraints.horizon_months}-month horizon, in {len(sentences)} "
        + ("sentence" if len(sentences) == 1 else "sentences")
        + ". Only structural checks follow; counterarguments need the analysis model."
    )
    assumptions = [
        (
            f"The thesis can be expressed through US-listed instruments tagged "
            f"{', '.join(themes[:4])}."
            if themes
            else "The thesis names no theme Hunch can map to instruments."
        )
    ]
    risks: list[str] = []
    if len(themes) <= 1:
        risks.append("The thesis rests on a single theme, so the basket will be concentrated.")
    if constraints.max_positions <= 5:
        risks.append(
            f"At most {constraints.max_positions} positions: each name carries a large share."
        )
    constraint_notes: list[str] = []
    if "decade" in lowered and constraints.horizon_months < 60:
        constraint_notes.append(
            f"The thesis speaks of a decade; the horizon is {constraints.horizon_months} months."
        )
    if HEDGING_WORDS.search(lowered) and not constraints.allow_leveraged_etf:
        constraint_notes.append(
            "The thesis mentions hedging or shorting, but leveraged and inverse products are "
            "not allowed."
        )
    if constraints.risk_level == "high" and constraints.cash_buffer >= 0.2:
        constraint_notes.append(
            f"A high risk level with a {constraints.cash_buffer:.0%} cash buffer pulls in "
            "opposite directions."
        )
    for exclusion in constraints.exclusions:
        theme = _overlaps(exclusion, themes)
        if theme is not None:
            constraint_notes.append(
                f"The exclusion '{exclusion}' overlaps the matched theme '{theme}'."
            )
    suggested_conditions = (
        []
        if conditions
        else [
            f"{theme} adoption or demand stalls for two consecutive quarters."
            for theme in themes[:3]
        ]
    )
    questions: list[str] = []
    if not TIME_WORDS.search(lowered):
        questions.append("Over what period do you expect this to play out?")
    if not LOSER_WORDS.search(lowered):
        questions.append("Who loses if you are right?")
    if len(themes) < 2:
        questions.append("Which industries or companies benefit first, and which only later?")
    if not conditions:
        questions.append("What would convince you that you are wrong?")
    return ThesisCritique(
        mode="heuristic",
        summary=summary,
        clarity=clarity,
        claims=claims,
        assumptions=assumptions,
        counterarguments=[],
        risks=risks[:MAX_ITEMS],
        suggested_conditions=suggested_conditions[:MAX_ITEMS],
        constraint_notes=constraint_notes[:MAX_ITEMS],
        questions=questions[:MAX_ITEMS],
    )


def critique_thesis(
    take: Take, *, mode: str | None = None, client: Any | None = None
) -> ThesisCritique:
    """The critique in the requested or configured mode (`inference` or `heuristic`)."""
    selected = mode or research_mode()
    if selected == "heuristic":
        return heuristic_critique(take)
    return inference_critique(take, client=client)


__all__ = [
    "ANALYSIS_TIMEOUT_SECONDS",
    "SYSTEM_PROMPT",
    "ClaimAssessment",
    "ThesisCritique",
    "critique_schema",
    "critique_thesis",
    "heuristic_critique",
    "inference_critique",
]
