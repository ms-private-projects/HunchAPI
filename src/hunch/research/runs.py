"""Researching a take and keeping the result: the first of the two build steps (ADR 0008).

``run_take_research`` reads the universe and the evidence, asks the configured researcher (the
recorded model call of the `research` role, or the deterministic heuristic) for the candidates and
stores the answer as a numbered ``TakeResearch`` row. It decides no weight and touches no
portfolio: construction (``hunch.portfolios.build``) is a separate step that starts from one
stored research. A take keeps every research it ran.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

from hunch.instruments import HunchInstrument
from hunch.instruments.services import ensure_universe
from hunch.market_data import ensure_daily_bars
from hunch.profiles import utc_now
from hunch.research import research_take
from hunch.research.models import CandidateInstrument, ResearchBrief, ResearchOutput
from hunch.research.sources import Evidence
from hunch.takes import Take
from hunch.takes.research import TakeResearch
from hunch.takes.services import TakeStateError

UTC = dt.timezone.utc


@dataclass(slots=True)
class ResearchResult:
    take: Take
    research: TakeResearch
    output: ResearchOutput


def take_research_rows(take_uid: uuid.UUID | str) -> list[TakeResearch]:
    """Every research of the take, oldest first."""
    rows = TakeResearch.filter(take_uid=uuid.UUID(str(take_uid)), limit=500)
    return sorted(rows, key=lambda row: row.number)


def latest_take_research(take_uid: uuid.UUID | str) -> TakeResearch | None:
    rows = take_research_rows(take_uid)
    return rows[-1] if rows else None


def research_for_build(
    take_uid: uuid.UUID | str, research_uid: uuid.UUID | str | None = None
) -> TakeResearch:
    """The stored research a construction starts from: the named one, which must belong to the
    take, or the take's latest. A take without research cannot be built."""
    if research_uid is None:
        row = latest_take_research(take_uid)
        if row is None:
            raise TakeStateError("Research the take before building it.")
        return row
    row = TakeResearch.get_by_uid(uuid.UUID(str(research_uid)))
    if row is None or str(row.take_uid) != str(uuid.UUID(str(take_uid))):
        raise LookupError(f"Research {research_uid} does not exist for this take.")
    return row


def research_output(row: TakeResearch) -> ResearchOutput:
    """The research as its researcher returned it, read back from the stored row."""
    return ResearchOutput(
        mode=row.mode,  # type: ignore[arg-type]
        brief=ResearchBrief.model_validate(row.brief_json or {}),
        candidates=[
            CandidateInstrument.model_validate(item) for item in (row.candidates_json or [])
        ],
        rationale_md=row.rationale_md or "",
        inference_request_uids=list(row.inference_request_uids or []),
        conversation_uid=row.conversation_uid,
        evidence=[Evidence.model_validate(item) for item in (row.evidence_json or [])],
        provider=row.provider,
        model=row.model,
    )


def run_take_research(
    take_uid: uuid.UUID | str,
    *,
    mode: str | None = None,
    now: dt.datetime | None = None,
    created_by: str | None = None,
) -> ResearchResult:
    """Research the take's thesis against the universe and store the result."""
    take = Take.get_by_uid(uuid.UUID(str(take_uid)))
    if take is None:
        raise LookupError(f"Take {take_uid} does not exist.")
    if take.status == "archived":
        raise TakeStateError("An archived take cannot be researched.")
    moment = (now or dt.datetime.now(UTC)).astimezone(UTC)

    instruments: list[HunchInstrument] = ensure_universe()
    # Research reads the stored bars (the quant evidence source). On the first research in an
    # Environment no bars exist yet and the read fails before the table has a registered update,
    # so write the universe's bars first.
    ensure_daily_bars([row.figi for row in instruments], end=moment.date())
    previous = take_research_rows(take.uid)
    number = (previous[-1].number + 1) if previous else 1
    output = research_take(take, instruments, mode=mode, number=number)
    row = TakeResearch.create(
        take_uid=take.uid,
        number=number,
        mode=output.mode,
        brief_json=output.brief.model_dump(),
        candidates_json=[candidate.model_dump() for candidate in output.candidates],
        rationale_md=output.rationale_md,
        evidence_json=[item.model_dump(mode="json") for item in output.evidence],
        inference_request_uids=output.inference_request_uids or None,
        conversation_uid=output.conversation_uid,
        provider=output.provider,
        model=output.model,
        created_by=created_by or "job",
        created_at=utc_now(),
    )
    return ResearchResult(take=take, research=row, output=output)


__all__ = [
    "ResearchResult",
    "latest_take_research",
    "research_for_build",
    "research_output",
    "run_take_research",
    "take_research_rows",
]
