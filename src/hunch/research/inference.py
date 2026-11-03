"""Research through Main Sequence recorded inference.

One structured completion per research: the model receives the thesis, the person's constraints
and the whole instrument universe, and must answer with a brief, candidates chosen from that
universe only, and a rationale. An answer that leaves the claims or a candidate's case empty is
retried once (ADR 0008). The platform records each request; their UIDs are kept on the research.
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
from hunch.research.sources import Evidence, evidence_block
from hunch.settings import MODEL_ROLE_RESEARCH, inference_environment_uid, model_role
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
- Write the rationale in Markdown for the person: the thesis in one paragraph, why these holdings \
express it, the roles, the main risks, and what would change your mind. Plain language, no hype.
- Ground every claim about a company in the evidence list when it covers it, citing its id in \
square brackets (for example [E3]) in the rationale and in each candidate's `citations`. When the \
evidence does not cover a point, say it rests on general knowledge; never invent a source.
- You are not an investment adviser; the person decides. Never promise returns.

Roles (each candidate's `role`):
- `pure_play`: the thesis is the instrument's business. Most of the company's revenue or profit \
comes from the very activity the thesis is about, or the fund holds only that theme. A company in \
a neighbouring industry is not a pure play (an electric utility is not a pure play on water), and \
neither is a diversified company with one exposed division. When the universe holds no pure play \
for the thesis, give no candidate this role and say so in the rationale.
- `supplier`: sells the inputs, equipment or services the pure plays depend on, including \
chokepoints that few others can supply.
- `enabler`: benefits second-hand when the thesis comes true (through its customers, its \
infrastructure or its sector) without the thesis being its main business.
- `hedge`: gains when the basket's main risk plays out, such as an inverse fund.
- `defensive`: holds its value whatever happens to the thesis, such as short-term Treasuries.

Fields of the answer. Every field is required and no text may be empty:
- `brief.claims`: the thesis broken into one to ten specific, checkable statements that must hold \
for the take to pay off, each a full sentence in your own words (for example "US data-centre \
power demand doubles by 2030.").
- `brief.beneficiaries` and `brief.losers`: the industries, kinds of company or named companies \
that gain or lose if the claims hold.
- `brief.keywords`: short search terms for the thesis: products, technologies, industries.
- `candidates[].ticker`: a ticker from the universe, exactly as written there.
- `candidates[].role`: one of the roles above, judged on the instrument's actual business.
- `candidates[].case`: one to three sentences, specific to this instrument, on how it expresses \
the thesis in its role: the business line, product or customers that tie it to the claims, with \
evidence ids in square brackets when the evidence covers it. Never a phrase that fits any company.
- `candidates[].risks`: what could make this instrument fail the thesis.
- `candidates[].conviction`: a relative sizing hint between 0 and 1.
- `candidates[].citations`: the evidence ids the case relies on; empty when no evidence applies.
- `rationale_md`: the Markdown rationale described in the rules.
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
                    "claims": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "minItems": 1,
                        "maxItems": 10,
                    },
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
                    "required": ["ticker", "role", "case", "risks", "conviction", "citations"],
                    "properties": {
                        "ticker": {"type": "string", "enum": list(tickers)},
                        "citations": {
                            "type": "array",
                            "items": {"type": "string"},
                            "maxItems": 20,
                        },
                        "role": {
                            "type": "string",
                            "enum": ["pure_play", "supplier", "enabler", "hedge", "defensive"],
                        },
                        "case": {"type": "string", "minLength": 1, "maxLength": 600},
                        "risks": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                        "conviction": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                },
            },
            "rationale_md": {"type": "string", "maxLength": 6000},
        },
    }


def _user_prompt(
    take: Take,
    constraints: TakeConstraints,
    instruments: Sequence[HunchInstrument],
    evidence: Sequence[Evidence] = (),
) -> str:
    return (
        f"# Take\n\nTitle: {take.title}\n\nThesis:\n{take.thesis_text}\n\n"
        f"# Constraints\n{json.dumps(constraints.model_dump(), indent=2)}\n\n"
        f"# Universe (choose tickers only from this list)\n{_universe_block(instruments)}\n\n"
        f"# Evidence (cite by id)\n{evidence_block(evidence)}\n\n"
        "Return the JSON object described by the schema."
    )


def _parse_answer(
    content: dict[str, Any], constraints: TakeConstraints, known: set[str]
) -> tuple[ResearchBrief, list[CandidateInstrument]]:
    """The brief and candidates of one answer: blank claims dropped, cases trimmed, and only the
    citations that name consulted evidence kept."""
    try:
        brief = ResearchBrief.model_validate(
            {**content.get("brief", {}), "horizon_months": constraints.horizon_months}
        )
        candidates = []
        for item in content["candidates"]:
            candidate = CandidateInstrument.model_validate(item)
            candidate.case = candidate.case.strip()
            candidate.citations = [c for c in candidate.citations if c in known]
            candidates.append(candidate)
    except Exception as exc:
        raise ResearchError("The research model answer does not match the contract.") from exc
    brief.claims = [claim.strip() for claim in brief.claims if claim.strip()]
    return brief, candidates


def _blank_fields(brief: ResearchBrief, candidates: Sequence[CandidateInstrument]) -> list[str]:
    """The required text an answer left empty, named by field."""
    blank = [] if brief.claims else ["brief.claims"]
    return blank + [f"the case of {item.ticker}" for item in candidates if not item.case]


def _retry_note(blank: Sequence[str]) -> str:
    return (
        "\n\n# Your previous answer was incomplete\n"
        f"It left these empty: {'; '.join(blank)}. Answer again in full, with at least one claim "
        "in `brief.claims` and a `case` for every candidate."
    )


class RecordedCompletion:
    """The parsed JSON answer of one recorded completion, its platform identifiers and its model."""

    def __init__(
        self,
        content: dict[str, Any],
        request_uid: str | None,
        conversation_uid: str | None,
        *,
        provider: str | None = None,
        model: str | None = None,
    ):
        self.content = content
        self.request_uid = request_uid
        self.conversation_uid = conversation_uid
        self.provider = provider
        self.model = model


def inference_client(client: Any | None = None) -> Any:
    from mainsequence.client import InferenceClient

    if client is not None:
        return client
    environment = inference_environment_uid()
    return (
        InferenceClient(organization_environment_uid=environment)
        if environment
        else InferenceClient()
    )


def recorded_completion(
    *,
    system: str,
    user: str,
    schema: dict[str, Any],
    operation: str,
    metadata: dict[str, Any],
    idempotency_prefix: str,
    timeout: int = 240,
    client: Any | None = None,
    what: str = "research",
    role: str = MODEL_ROLE_RESEARCH,
) -> RecordedCompletion:
    """One recorded, schema-constrained completion on the role's model.

    The role (`hunch.settings.model_role`) decides the provider, model, thinking level and
    credential, so each kind of call can run on a different model. Raises ``ResearchError`` on any
    failure.
    """
    inference = inference_client(client)
    try:
        selection = model_role(role)
    except ValueError as exc:
        raise ResearchError(f"The {what} model role is misconfigured: {exc}") from exc
    try:
        result = inference.complete(
            provider=selection.provider,
            model=selection.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            thinking_level=selection.thinking,
            custom_id=selection.credential,
            response_schema=schema,
            metadata={"operation": operation, "model_role": role, **metadata},
            idempotency_key=f"{idempotency_prefix}-{uuid.uuid4().hex[:8]}",
            timeout=timeout,
        )
    except Exception as exc:  # the client's own errors carry provider internals
        raise ResearchError(f"The {what} model call failed ({type(exc).__name__}).") from exc
    if result.status != "completed" or not result.content_available or not result.output:
        raise ResearchError(f"The {what} model call did not complete (status {result.status}).")
    content = result.output.get("content") if isinstance(result.output, dict) else None
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except ValueError as exc:
            raise ResearchError(f"The {what} model returned no JSON object.") from exc
    if not isinstance(content, dict):
        raise ResearchError(f"The {what} model returned no JSON object.")
    return RecordedCompletion(
        content,
        str(result.request_uid) if result.request_uid else None,
        str(result.conversation_uid) if result.conversation_uid else None,
        provider=str(getattr(result, "provider", "") or selection.provider),
        model=str(getattr(result, "model", "") or selection.model),
    )


def inference_research(
    take: Take,
    instruments: Sequence[HunchInstrument],
    *,
    number: int = 1,
    client: Any | None = None,
    evidence: Sequence[Evidence] = (),
) -> ResearchOutput:
    """One recorded completion, retried once when the answer leaves required text empty; raises
    ``ResearchError`` when no usable answer comes back.

    `number` is the research's ordinal for the take (ADR 0008); every recorded call of the
    research carries it in its key and metadata. A provider's strict mode may not enforce the
    schema's `minItems` and `minLength`, so the claims and every candidate's case are checked
    here; the retry says which fields were empty, and a second incomplete answer is refused.
    """
    constraints = TakeConstraints.model_validate(take.constraints_json or {})
    tradable = [row for row in instruments if row.is_tradable]
    if not tradable:
        raise ResearchError("The instrument universe is empty.")
    user = _user_prompt(take, constraints, tradable, evidence)
    schema = response_schema([row.ticker for row in tradable])
    known = {item.id for item in evidence}
    prompt, idempotency_prefix = user, f"hunch-take-{take.uid}-research-{number}"
    request_uids: list[str] = []
    for attempt in (1, 2):
        completion = recorded_completion(
            system=SYSTEM_PROMPT,
            user=prompt,
            schema=schema,
            operation="hunch-take-research",
            metadata={"take_uid": str(take.uid), "research_number": number, "attempt": attempt},
            idempotency_prefix=idempotency_prefix,
            client=client,
        )
        if completion.request_uid:
            request_uids.append(completion.request_uid)
        content = completion.content
        brief, candidates = _parse_answer(content, constraints, known)
        blank = _blank_fields(brief, candidates)
        if not blank:
            break
        prompt = user + _retry_note(blank)
        idempotency_prefix = f"hunch-take-{take.uid}-research-{number}-retry"
    else:
        raise ResearchError(
            "The research model left the brief's claims or a candidate's case empty twice."
        )
    return ResearchOutput(
        mode="inference",
        brief=brief,
        candidates=candidates,
        rationale_md=str(content.get("rationale_md") or ""),
        inference_request_uids=request_uids,
        conversation_uid=completion.conversation_uid,
        evidence=list(evidence),
        provider=completion.provider,
        model=completion.model,
    )


__all__ = [
    "RecordedCompletion",
    "SYSTEM_PROMPT",
    "inference_client",
    "inference_research",
    "recorded_completion",
    "response_schema",
]
