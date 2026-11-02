"""Take research: every study of the target universe Hunch made for a take.

Research is the first of the two independent steps that turn a thesis into a portfolio (ADR
0008): it reads the universe and the evidence and answers with the candidate instruments, their
roles, cases, risks and conviction, a brief of the thesis and a rationale. It decides no weight.
Portfolio construction (``hunch.portfolios.build``) is the second step: it takes one stored
research and the take's constraints and builds the basket. A take keeps every research it ran,
numbered, so a person can research again without rebuilding and build again from a research they
kept.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, ClassVar

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from hunch.metatables import HunchMarketsMetaTableMixin, ProjectStorageNameMixin
from hunch.profiles import utc_now
from hunch.settings import PROJECT_NAMESPACE_SLUG
from hunch.takes import TakeTable
from msm.api.base import MarketsMetaTableRow
from msm.base import MarketsBase, markets_table_args, new_markets_uid


class TakeResearchTable(ProjectStorageNameMixin, HunchMarketsMetaTableMixin, MarketsBase):
    """One row per research of a take's target universe."""

    __project_storage_concept__ = "take_research"
    __markets_base_identifier__ = "HunchTakeResearch"
    __metatable_description__ = (
        "One row per research of a take's target universe: the thesis brief, the candidate "
        "instruments with their roles, cases, risks, conviction and citations, the rationale, the "
        "evidence consulted, the model that answered and the recorded inference requests behind "
        "it. Portfolio construction reads one of these rows; research itself decides no weight."
    )
    __metatable_labels__ = ["hunch", "takes", "research"]
    __metatable_extra_hash_components__: ClassVar[dict[str, str]] = {
        "storage_name": f"{PROJECT_NAMESPACE_SLUG}_take_research",
    }
    __table_args__ = markets_table_args(
        "HunchTakeResearch",
        Index(None, "take_uid", "number", unique=True),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=new_markets_uid
    )
    take_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{TakeTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
    )
    number: Mapped[int] = mapped_column(
        Integer, nullable=False, info={"description": "1, 2, ... per take, in research order."}
    )
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, info={"description": "inference or heuristic."}
    )
    brief_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        info={"description": "The thesis parsed: claims, beneficiaries, losers, keywords."},
    )
    candidates_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        info={"description": "[{ticker, role, case, risks, conviction, citations}]."},
    )
    rationale_md: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    inference_request_uids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    conversation_uid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="job",
        info={"description": "job, user or agent."},
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class TakeResearch(MarketsMetaTableRow):
    """Typed row-operation wrapper for ``TakeResearchTable``."""

    __table__: ClassVar[type[TakeResearchTable]] = TakeResearchTable
    __required_tables__: ClassVar[list[type[Any]]] = [TakeTable, TakeResearchTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("take_uid", "number")

    take_uid: uuid.UUID
    number: int
    mode: str
    brief_json: dict[str, Any]
    candidates_json: list[dict[str, Any]]
    rationale_md: str = ""
    evidence_json: list[dict[str, Any]] | None = None
    inference_request_uids: list[str] | None = None
    conversation_uid: str | None = None
    provider: str | None = None
    model: str | None = None
    created_by: str = "job"
    created_at: dt.datetime | None = None


def project_research_models() -> list[type[Any]]:
    return [TakeResearchTable]


__all__ = ["TakeResearch", "TakeResearchTable", "project_research_models"]
